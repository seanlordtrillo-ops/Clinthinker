from __future__ import annotations

import asyncio
import csv
import hashlib
import http.client
import io
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from sklearn import __version__ as sklearn_version

from .. import database
from ..database import UPLOADS, connect, get_settings, initialize, save_settings
from ..core.checks import checks, suppress_check_exception_logging
from ..core import errors as _core_errors
from ..core import logging_setup as _core_logging_setup
from .. import diagnostics as _diagnostics
from ..ml import *
from ..parsing import MAX_UPLOAD_BYTES, extract_lesson_features, extract_text, read_limited
from app.questions import *
from ..schemas import *
from ..services.updates import *

import importlib

def _compat_main():
    return importlib.import_module("app.main")
from ..services.uploads import _is_exam_upload
from app.progress import record_topic_likelihood

router = APIRouter()


def _remember_topic_likelihood(lesson_ids: list[str], likely_topics: list[dict]) -> None:
    """Keep each lesson's topic likelihood for My Progress. Never blocks generation."""
    try:
        record_topic_likelihood(lesson_ids, likely_topics)
    except Exception:
        logging.getLogger(__name__).warning("Could not save topic likelihood", exc_info=True)


_question_batches: OrderedDict[str, dict] = OrderedDict()
_MAX_QUESTION_BATCHES = 25
_QUESTION_BATCH_UNAVAILABLE_DETAIL = (
    "This practice set is no longer available (the app was restarted or newer sets "
    "replaced it). Generate the questions again to save them or reveal the answer key."
)


@checks(
    expected="Generated question result",
    probable_cause="Question generation failed",
)
@router.post("/api/questions/generate")
def generate_practice_questions(request: GenerateQuestionsRequest) -> dict:
    if len(set(request.upload_ids)) != len(request.upload_ids):
        raise HTTPException(status_code=422, detail="Select each course material only once.")
    if len(set(request.lesson_upload_ids)) != len(request.lesson_upload_ids):
        raise HTTPException(status_code=422, detail="Select each lesson only once.")
    lesson_ids = list(dict.fromkeys(
        request.lesson_upload_ids
        + ([request.lesson_upload_id] if request.lesson_upload_id else [])
    ))
    if any(lesson_id not in request.upload_ids for lesson_id in lesson_ids):
        raise HTTPException(status_code=422, detail="Include every lesson in the source selection.")
    if lesson_ids and set(request.upload_ids) != set(lesson_ids):
        raise HTTPException(
            status_code=422,
            detail="Lesson generation accepts only selected lesson files as content sources.",
        )
    if request.lesson_only and not lesson_ids:
        raise HTTPException(status_code=422, detail="Select at least one lesson.")
    try:
        with connect() as db:
            if request.training_dataset_id == "builtin":
                dataset_name = "Built-in examples"
                examples = list(BUILTIN_TRAINING_EXAMPLES)
                dataset_rows = []
            else:
                dataset = db.execute(
                    "SELECT name FROM training_datasets WHERE id=?",
                    (request.training_dataset_id,),
                ).fetchone()
                if not dataset:
                    raise HTTPException(status_code=404, detail="Training dataset not found.")
                dataset_name = dataset["name"]
                dataset_rows = db.execute(
                    "SELECT text, topic, source_material_id, source_material_name "
                    "FROM training_examples WHERE dataset_id=? ORDER BY rowid",
                    (request.training_dataset_id,),
                ).fetchall()
                examples = [(row["text"], row["topic"]) for row in dataset_rows]
            upload_rows = []
            for upload_id in request.upload_ids:
                upload = db.execute(
                    "SELECT id, name, stored_path, is_exam FROM uploads WHERE id=?",
                    (upload_id,),
                ).fetchone()
                if not upload:
                    raise HTTPException(status_code=404, detail="A selected course material was not found.")
                upload_rows.append(dict(upload))
            lesson_uploads = [
                upload for upload in upload_rows if upload["id"] in lesson_ids
            ]
            lesson_texts = {}
            lesson_features = {
                "emphasized_terms": [],
                "heading_terms": [],
                "list_terms": [],
            }
            for lesson_upload in lesson_uploads:
                lesson_path = Path(lesson_upload["stored_path"]).resolve()
                if lesson_path.parent != _compat_main().UPLOADS.resolve():
                    raise HTTPException(status_code=500, detail="The saved lesson path is invalid.")
                try:
                    lesson_content = lesson_path.read_bytes()
                    lesson_texts[lesson_upload["id"]] = _compat_main().extract_text(
                        lesson_upload["name"], lesson_content
                    )
                    features = _compat_main().extract_lesson_features(
                        lesson_upload["name"], lesson_content
                    )
                    for key in lesson_features:
                        lesson_features[key].extend(features[key])
                except HTTPException:
                    raise
                except OSError as error:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Could not read lesson {lesson_upload['name']}: {error}",
                    ) from error
            relevant_source_ids = lesson_ids or request.upload_ids
            placeholders = ",".join("?" for _ in relevant_source_ids)
            saved_texts = [
                row["question_text"]
                for row in db.execute(
                    "SELECT question_text FROM generated_questions "
                    f"WHERE source_material_id IN ({placeholders})",
                    tuple(relevant_source_ids),
                ).fetchall()
            ]
            saved_excerpt_rows = db.execute(
                "SELECT support_excerpt, question_type, question_direction, question_text, "
                "choices, correct_answer, source_material_id, created_at "
                "FROM generated_questions "
                f"WHERE source_material_id IN ({placeholders}) "
                "AND support_excerpt != ''",
                tuple(relevant_source_ids),
            ).fetchall()
            used_excerpts = [
                {
                    "support_excerpt": row["support_excerpt"],
                    "question_type": row["question_type"],
                    "question_direction": row["question_direction"],
                    "question_text": row["question_text"],
                    "choices": json.loads(row["choices"]),
                    "correct_answer": row["correct_answer"],
                    "source_material_id": row["source_material_id"],
                    "use_count": 1,
                    "last_used_at": row["created_at"],
                }
                for row in saved_excerpt_rows
            ]
            used_question_forms = [
                (
                    row["support_excerpt"],
                    row["question_type"],
                    row["question_direction"]
                    or (
                        "statement"
                        if row["question_type"] == "True or False"
                        else "definition_to_term"
                    ),
                )
                for row in saved_excerpt_rows
            ]
            recent_batches = [
                batch for batch in reversed(_question_batches.values())
                if set(batch.get("upload_ids", ())).intersection(relevant_source_ids)
            ][:3]
            for batch in recent_batches:
                for item in batch.get("result", {}).get("questions", []):
                    if item.get("id") in batch.get("saved_question_ids", set()):
                        continue
                    source_id = item.get("source_material_id")
                    if source_id is not None and source_id not in relevant_source_ids:
                        continue
                    if source_id is None and not set(
                        batch.get("upload_ids", ())
                    ).issubset(relevant_source_ids):
                        continue
                    excluded_sources = batch.get("novelty_excluded_source_ids", set())
                    if source_id in excluded_sources or (
                        source_id is None
                        and set(batch.get("upload_ids", ())).intersection(excluded_sources)
                    ):
                        continue
                    excerpt = str(item.get("support_excerpt", "")).strip()
                    if excerpt:
                        used_excerpts.append({
                            "support_excerpt": excerpt,
                            "question_type": item.get("question_type", ""),
                            "question_direction": item.get("question_direction", ""),
                            "question_text": item.get("question_text", ""),
                            "choices": item.get("choices", []),
                            "correct_answer": item.get("correct_answer", ""),
                            "source_material_id": source_id,
                            "use_count": 1,
                            "last_used_at": batch.get("created_at", ""),
                        })
                        used_question_forms.append(
                            (
                                excerpt,
                                str(item.get("question_type", "")),
                                str(item.get("question_direction", ""))
                                or (
                                    "statement"
                                    if item.get("question_type") == "True or False"
                                    else "definition_to_term"
                                ),
                            )
                        )
            preference_feedback = [
                dict(row)
                for row in db.execute(
                    "SELECT rating, question_type, difficulty, wording_pattern "
                    "FROM question_feedback"
                ).fetchall()
            ]
        decision_policy = _compat_main().get_decision_policy(
            {"id": request.training_dataset_id, "examples": examples}
        )

        source_upload_rows = list(upload_rows)
        if lesson_ids:
            with connect() as db:
                exam_rows = db.execute(
                    "SELECT id, name, stored_path, is_exam FROM uploads"
                ).fetchall()
            existing_upload_ids = set(lesson_ids)
            source_upload_rows.extend(
                dict(row) for row in exam_rows
                if row["id"] not in existing_upload_ids
                and _is_exam_upload(row)
            )

        sources = []
        source_characters = 0
        exam_sources = []
        skipped_exam_files = []
        exam_characters = 0
        for upload in source_upload_rows:
            is_lesson = upload["id"] in lesson_ids
            is_exam = _is_exam_upload(upload) and not is_lesson
            path = Path(upload["stored_path"]).resolve()
            if path.parent != _compat_main().UPLOADS.resolve():
                raise HTTPException(status_code=500, detail="A saved course material could not be read.")
            try:
                text = lesson_texts[upload["id"]] if is_lesson else _compat_main().extract_text(
                    upload["name"], path.read_bytes()
                )
            except HTTPException as error:
                if lesson_ids and is_exam:
                    skipped_exam_files.append(upload["name"])
                    continue
                raise HTTPException(
                    status_code=error.status_code,
                    detail=f"Could not extract readable text from {upload['name']}.",
                ) from error
            except OSError as error:
                raise HTTPException(
                    status_code=500, detail=f"Could not read saved course material {upload['name']}."
                ) from error
            if lesson_ids and is_exam:
                if exam_characters + len(text) <= 500_000:
                    exam_sources.append(
                        {"id": upload["id"], "name": upload["name"], "text": text}
                    )
                    exam_characters += len(text)
                else:
                    skipped_exam_files.append(upload["name"])
                continue
            source_characters += len(text)
            if source_characters > 500_000:
                raise HTTPException(
                    status_code=413,
                    detail="Selected course materials exceed the 500,000 character analysis limit.",
                )
            sources.append({
                "id": upload["id"],
                "name": upload["name"],
                "text": text,
                "kind": "lesson" if is_lesson else "course",
            })
        if not lesson_ids:
            for index, row in enumerate(dataset_rows, start=1):
                sources.append(
                    {
                        "id": row["source_material_id"],
                        "name": row["source_material_name"] or f"{dataset_name} Â· Example {index}",
                        "text": row["text"],
                        "kind": "training",
                    }
                )

        training_metrics = {}
        classifier_examples = examples
        exam_passages_added = 0
        if lesson_ids:
            classifier_examples, exam_passages_added = (
                _compat_main().augment_training_examples_with_exam_passages(
                    examples,
                    exam_sources,
                    training_metrics,
                    dataset_id=request.training_dataset_id,
                    decision_policy=decision_policy,
                )
            )
        exam_question_patterns = (
            _compat_main().extract_exam_question_patterns(
                exam_sources,
                classifier_examples,
                training_metrics,
                dataset_id=request.training_dataset_id,
                decision_policy=decision_policy,
            )
            if lesson_ids and request.use_exam_style else []
        )
        result = _compat_main().generate_questions(
            requested_count=request.number_of_questions,
            question_type=request.question_type,
            difficulty=request.difficulty,
            topic_filter=request.topic,
            per_topic=request.questions_per_topic,
            training_examples=classifier_examples,
            dataset_id=request.training_dataset_id,
            dataset_name=dataset_name,
            sources=sources,
            lesson_mode=bool(lesson_ids),
            training_metrics=training_metrics,
            saved_question_texts=saved_texts,
            preference_feedback=preference_feedback,
            similarity_threshold=request.similarity_threshold,
            allow_repeats=request.allow_repeats,
            used_excerpts=used_excerpts,
            used_question_forms=used_question_forms,
            random_seed=uuid.uuid4().int,
            priority_weights=request.priority_weights.model_dump(),
            decision_policy=decision_policy,
        )
        if lesson_ids:
            lesson_text = "\n\n".join(
                lesson_texts[upload["id"]] for upload in lesson_uploads
            )
            recent_topics = [row["topic"] for row in _compat_main().database_recent_question_topics()]
            lesson_ranking = _compat_main().rank_lesson_likelihood(
                result["questions"],
                lesson_text,
                classifier_examples,
                exam_sources=exam_sources if request.use_exam_style else [],
                recent_question_topics=recent_topics,
                emphasized_terms=lesson_features["emphasized_terms"],
                heading_terms=lesson_features["heading_terms"],
                list_terms=lesson_features["list_terms"],
                training_metrics=training_metrics,
                dataset_id=request.training_dataset_id,
                decision_policy=decision_policy,
            )
            result.update(lesson_ranking)
            _remember_topic_likelihood(lesson_ids, lesson_ranking.get("likely_topics", []))
            result["skipped_exam_files"] = skipped_exam_files
            result["classifier_training"] = {
                "mode": "on-demand during generation; fitted models are cached in memory",
                "fit_seconds": round(training_metrics.get("fit_seconds", 0.0), 3),
                "fit_count": training_metrics.get("fit_count", 0),
                "cache_hits": training_metrics.get("cache_hits", 0),
                "exam_passages_added": exam_passages_added,
                "minimum_exam_label_confidence": decision_policy["confidence_threshold"],
            }
            result["style_reference_enabled"] = request.use_exam_style
            result["style_reference_files"] = len(exam_sources) if request.use_exam_style else 0
            result["question_pattern_count"] = len(exam_question_patterns)
            lesson_names = [upload["name"] for upload in lesson_uploads]
            result["lesson_names"] = lesson_names
            result["lesson_name"] = lesson_names[0] if len(lesson_names) == 1 else None
        result["preference_learning"] = {
            "ratings_recorded": len(preference_feedback),
            "applied": bool(preference_feedback),
        }
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    generation_id = str(uuid.uuid4())
    result["generation_id"] = generation_id
    _question_batches[generation_id] = {
        "result": result,
        "dataset_id": request.training_dataset_id,
        "upload_ids": request.upload_ids,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "topic": request.topic,
        "source_file": (
            ", ".join(upload["name"] for upload in lesson_uploads)
            if lesson_ids else ", ".join(upload["name"] for upload in upload_rows)
        ),
        "difficulty": request.difficulty,
        "question_type": request.question_type,
        "saved_question_ids": set(),
        "novelty_excluded_source_ids": set(),
    }
    _question_batches.move_to_end(generation_id)
    while len(_question_batches) > _MAX_QUESTION_BATCHES:
        _question_batches.popitem(last=False)
    public_result = {**result}
    public_result["questions"] = [
        {
            key: value for key, value in item.items()
            if key not in {
                "correct_answer",
                "support_excerpt",
                "source_content",
                "supported_statement",
                "false_statement",
                "false_basis",
                "source_defined_terms",
                "question_direction",
                "_alternate_form",
            }
        }
        for item in result["questions"]
    ]
    return public_result


@router.get("/api/questions/preferences")
def get_question_preferences() -> dict:
    with connect() as db:
        rows = db.execute(
            "SELECT question_type, difficulty, wording_pattern, question_length, "
            "answer_length, rating "
            "FROM question_feedback"
        ).fetchall()
    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for row in rows:
        for feature, value in (
            ("question_type", row["question_type"]),
            ("difficulty", row["difficulty"]),
            ("wording_pattern", row["wording_pattern"]),
            ("question_length", row["question_length"]),
            ("answer_length", row["answer_length"]),
        ):
            counts = grouped.setdefault(
                (feature, value), {"positive": 0, "negative": 0}
            )
            counts["positive" if row["rating"] > 0 else "negative"] += 1
    learned = [
        {"feature": feature, "value": value, **counts}
        for (feature, value), counts in grouped.items()
        if counts["positive"] > counts["negative"]
    ]
    learned.sort(
        key=lambda item: (
            -(item["positive"] - item["negative"]),
            item["feature"],
            item["value"],
        )
    )
    return {
        "ratings_recorded": len(rows),
        "positive_ratings": sum(row["rating"] > 0 for row in rows),
        "negative_ratings": sum(row["rating"] < 0 for row in rows),
        "learned_preferences": learned,
    }


@router.post("/api/questions/feedback")
def save_question_feedback(request: QuestionFeedbackRequest) -> dict:
    question = None
    if request.generation_id:
        batch = _question_batches.get(request.generation_id)
        if batch:
            question = next(
                (
                    item for item in batch["result"]["questions"]
                    if item["id"] == request.question_id
                ),
                None,
            )
    if question is None:
        with connect() as db:
            row = db.execute(
                "SELECT id, question_text, question_type, difficulty, correct_answer "
                "FROM generated_questions WHERE id=?",
                (request.question_id,),
            ).fetchone()
        question = dict(row) if row else None
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    features = _compat_main().question_preference_features(question)
    with connect() as db:
        db.execute(
            "INSERT INTO question_feedback("
            "question_id, rating, question_type, difficulty, wording_pattern, "
            "question_length, answer_length"
            ") VALUES(?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(question_id) DO UPDATE SET "
            "rating=excluded.rating, question_type=excluded.question_type, "
            "difficulty=excluded.difficulty, wording_pattern=excluded.wording_pattern, "
            "question_length=excluded.question_length, answer_length=excluded.answer_length, "
            "rated_at=datetime('now')",
            (
                request.question_id,
                request.rating,
                features["question_type"],
                features["difficulty"],
                features["wording_pattern"],
                features["question_length"],
                features["answer_length"],
            ),
        )
    return {
        **get_question_preferences(),
        "question_id": request.question_id,
        "rating": request.rating,
    }


@router.delete("/api/questions/feedback")
def clear_question_feedback() -> dict:
    with connect() as db:
        db.execute("DELETE FROM question_feedback")
    return get_question_preferences()


@checks(
    expected="Question history reset",
    probable_cause="Question history could not be reset",
)
@router.post("/api/questions/history/reset")
def reset_question_history(request: ResetQuestionHistoryRequest) -> dict:
    if len(set(request.upload_ids)) != len(request.upload_ids):
        raise HTTPException(status_code=422, detail="Select each lesson only once.")
    source_ids = set(request.upload_ids)
    placeholders = ",".join("?" for _ in source_ids)
    with connect() as db:
        existing_ids = {
            row["id"]
            for row in db.execute(
                f"SELECT id FROM uploads WHERE id IN ({placeholders})",
                tuple(source_ids),
            ).fetchall()
        }
        if existing_ids != source_ids:
            raise HTTPException(status_code=404, detail="A selected lesson was not found.")
        changed = db.execute(
            "UPDATE generated_questions SET support_excerpt='', question_direction='' "
            f"WHERE source_material_id IN ({placeholders}) "
            "AND (support_excerpt != '' OR question_direction != '')",
            tuple(source_ids),
        ).rowcount
    for batch in _question_batches.values():
        matching_sources = source_ids.intersection(batch.get("upload_ids", ()))
        if matching_sources:
            batch.setdefault("novelty_excluded_source_ids", set()).update(matching_sources)
    return {"reset_count": changed, "upload_ids": request.upload_ids}


@router.post("/api/questions/answers")
def reveal_question_answers(request: SaveQuestionsRequest) -> dict:
    batch = _question_batches.get(request.generation_id)
    if not batch:
        raise HTTPException(
            status_code=410,
            detail=_QUESTION_BATCH_UNAVAILABLE_DETAIL,
        )
    questions = {item["id"]: item for item in batch["result"]["questions"]}
    if not set(request.question_ids).issubset(questions):
        raise HTTPException(status_code=422, detail="The selected generated questions are invalid.")
    return {
        "answers": {
            question_id: questions[question_id]["correct_answer"]
            for question_id in request.question_ids
        },
        "explanations": {
            question_id: questions[question_id]["support_excerpt"]
            for question_id in request.question_ids
        },
    }


@checks(
    expected="Saved question result",
    probable_cause="Question saving failed",
)
@router.post("/api/questions/save")
def save_practice_questions(request: SaveQuestionsRequest) -> dict:
    batch = _question_batches.get(request.generation_id)
    if not batch:
        raise HTTPException(
            status_code=410,
            detail=_QUESTION_BATCH_UNAVAILABLE_DETAIL,
        )
    requested_ids = set(request.question_ids)
    questions = {item["id"]: item for item in batch["result"]["questions"]}
    if len(request.question_ids) != len(requested_ids) or not requested_ids.issubset(questions):
        raise HTTPException(status_code=422, detail="The selected generated questions are invalid.")

    try:
        with connect() as db:
            if batch["dataset_id"] != "builtin" and not db.execute(
                "SELECT 1 FROM training_datasets WHERE id=?", (batch["dataset_id"],)
            ).fetchone():
                raise HTTPException(status_code=409, detail="The source training dataset was deleted.")
            placeholders = ",".join("?" for _ in batch["upload_ids"])
            existing_uploads = {
                row["id"]
                for row in db.execute(
                    f"SELECT id FROM uploads WHERE id IN ({placeholders})",
                    tuple(batch["upload_ids"]),
                ).fetchall()
            }
            if existing_uploads != set(batch["upload_ids"]):
                raise HTTPException(status_code=409, detail="A source course material was deleted.")
            selected = [questions[item] for item in request.question_ids]
            placeholders = ",".join("?" for _ in selected)
            duplicates = db.execute(
                f"SELECT 1 FROM generated_questions WHERE question_text IN "
                f"({placeholders}) LIMIT 1",
                tuple(item["question_text"] for item in selected),
            ).fetchone()
            if duplicates:
                raise HTTPException(status_code=409, detail="One or more questions were already saved.")
            db.execute(
                "INSERT OR IGNORE INTO saved_sessions("
                "id, title, created_at, topic, source_file, difficulty, question_type, question_count"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, 0)",
                (
                    request.generation_id,
                    f"{batch['topic']} practice questions",
                    batch["created_at"],
                    batch["topic"],
                    batch["source_file"],
                    batch["difficulty"],
                    batch["question_type"],
                ),
            )
            for item in selected:
                if (
                    item["support_excerpt"].casefold() not in item["source_reference"].casefold()
                    or item["support_excerpt"].casefold() not in item["source_content"].casefold()
                ):
                    raise HTTPException(status_code=422, detail="A generated question failed source validation.")
                db.execute(
                    "INSERT INTO generated_questions("
                    "id, question_text, question_type, topic, difficulty, choices, "
                    "correct_answer, priority_score, confidence_score, source_dataset_id, "
                    "source_dataset_name, source_material_id, source_material_name, source_reference, "
                    "session_id, support_excerpt, question_direction"
                    ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item["id"], item["question_text"], item["question_type"],
                        item["topic"], item["difficulty"], json.dumps(item["choices"]),
                        item["correct_answer"], item["priority_score"], item["confidence_score"],
                        item["source_dataset_id"], item["source_dataset_name"],
                        item["source_material_id"], item["source_material_name"],
                        item["source_reference"],
                        request.generation_id,
                        (
                            ""
                            if item.get("source_material_id")
                            in batch.get("novelty_excluded_source_ids", set())
                            else item["support_excerpt"]
                        ),
                        (
                            ""
                            if item.get("source_material_id")
                            in batch.get("novelty_excluded_source_ids", set())
                            else item.get("question_direction", "")
                        ),
                    ),
                )
            db.execute(
                "UPDATE saved_sessions SET question_count=("
                "SELECT COUNT(*) FROM generated_questions WHERE session_id=?"
                ") WHERE id=?",
                (request.generation_id, request.generation_id),
            )
            batch.setdefault("saved_question_ids", set()).update(requested_ids)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=500, detail="Could not save generated questions locally.") from error
    return {"saved_count": len(requested_ids), "question_ids": request.question_ids}


@router.get("/api/questions/saved")
def list_saved_questions(
    include_answers: bool = False,
    session_id: str | None = None,
) -> dict:
    with connect() as db:
        sessions = db.execute(
            "SELECT id, title, created_at, topic, source_file, difficulty, "
            "question_type, question_count FROM saved_sessions "
            "ORDER BY created_at DESC, rowid DESC"
        ).fetchall()
        rows = db.execute(
            "SELECT q.id, q.question_text, q.question_type, q.topic, q.difficulty, q.choices, "
            "correct_answer, priority_score, confidence_score, source_dataset_name, "
            "source_material_name, source_reference, created_at, session_id, "
            "f.rating AS feedback_rating "
            "FROM generated_questions q LEFT JOIN question_feedback f ON f.question_id=q.id "
            "ORDER BY q.created_at, q.rowid"
        ).fetchall()
    questions_by_session: dict[str, list[dict]] = {}
    for row in rows:
        item = dict(row)
        item["choices"] = json.loads(item["choices"])
        if not include_answers or (session_id and item["session_id"] != session_id):
            item.pop("correct_answer")
        questions_by_session.setdefault(item.pop("session_id"), []).append(item)
    return {
        "sessions": [
            {
                **dict(session),
                "questions": questions_by_session.get(session["id"], []),
            }
            for session in sessions
        ]
    }


@router.put("/api/questions/sessions/{session_id}")
def rename_saved_session(session_id: str, request: RenameSavedSessionRequest) -> dict:
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Session title cannot be blank.")
    with connect() as db:
        cursor = db.execute(
            "UPDATE saved_sessions SET title=? WHERE id=?",
            (title, session_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Saved question session not found.")
    return {"id": session_id, "title": title}


@router.delete("/api/questions/sessions/{session_id}")
def delete_saved_session(session_id: str) -> dict:
    with connect() as db:
        cursor = db.execute("DELETE FROM saved_sessions WHERE id=?", (session_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Saved question session not found.")
        db.execute(
            "DELETE FROM question_feedback WHERE question_id IN "
            "(SELECT id FROM generated_questions WHERE session_id=?)",
            (session_id,),
        )
        db.execute("DELETE FROM generated_questions WHERE session_id=?", (session_id,))
    return {"deleted": session_id}
