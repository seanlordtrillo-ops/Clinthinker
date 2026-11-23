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
from ..csv_import import CsvImportError, read_labeled_csv
from ..database import UPLOADS, connect, get_settings, initialize, save_settings
from ..core.checks import checks, suppress_check_exception_logging
from ..core import errors as _core_errors
from ..core import logging_setup as _core_logging_setup
from .. import diagnostics as _diagnostics
from ..ml import *
from ..ml import dataset_hash, evaluate_classifier
from ..parsing import MAX_UPLOAD_BYTES, extract_lesson_features, extract_text, read_limited
from ..questions import *
from ..schemas import *
from ..services.updates import *

from app import main as _main

router = APIRouter()


@router.get("/api/training-datasets")
def list_training_datasets() -> list[dict]:
    with connect() as db:
        rows = db.execute(
            """
            SELECT d.id, d.name, d.source_type, d.created_at,
                   COUNT(e.id) AS example_count,
                   COUNT(DISTINCT e.topic) AS topic_count
            FROM training_datasets d
            LEFT JOIN training_examples e ON e.dataset_id=d.id
            GROUP BY d.id
            ORDER BY d.created_at DESC, d.rowid DESC
            """
        ).fetchall()
    return [
        {
            "id": "builtin",
            "name": "Built-in examples",
            "source_type": "built-in",
            "example_count": BUILTIN_TRAINING_EXAMPLE_COUNT,
            "topic_count": len(BUILTIN_TRAINING_TOPICS),
            "topics": BUILTIN_TRAINING_TOPICS,
        },
        *[dict(row) for row in rows],
    ]


@router.post("/api/training-datasets/evaluate")
def evaluate_training_dataset(request: EvaluateDatasetRequest) -> dict:
    if request.training_dataset_id == "builtin":
        dataset_name = "Built-in examples"
        examples = list(BUILTIN_TRAINING_EXAMPLES)
    else:
        with connect() as db:
            dataset = db.execute(
                "SELECT name FROM training_datasets WHERE id=?",
                (request.training_dataset_id,),
            ).fetchone()
            if not dataset:
                raise HTTPException(status_code=404, detail="Training dataset not found.")
            rows = db.execute(
                "SELECT text, topic FROM training_examples "
                "WHERE dataset_id=? ORDER BY rowid",
                (request.training_dataset_id,),
            ).fetchall()
        dataset_name = dataset["name"]
        examples = [(row["text"], row["topic"]) for row in rows]
    try:
        report = evaluate_classifier(examples)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    policy = report["decision_policy"]
    with connect() as db:
        db.execute(
            "INSERT INTO model_calibration("
            "dataset_id, dataset_hash, svm_temperature, ensemble_temperature, "
            "confidence_threshold, min_margin, disagreement_abstain, "
            "target_precision, low_reliability, sklearn_version) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(dataset_id) DO UPDATE SET "
            "dataset_hash=excluded.dataset_hash, "
            "svm_temperature=excluded.svm_temperature, "
            "ensemble_temperature=excluded.ensemble_temperature, "
            "confidence_threshold=excluded.confidence_threshold, "
            "min_margin=excluded.min_margin, "
            "disagreement_abstain=excluded.disagreement_abstain, "
            "target_precision=excluded.target_precision, "
            "low_reliability=excluded.low_reliability, "
            "sklearn_version=excluded.sklearn_version, "
            "created_at=datetime('now')",
            (
                request.training_dataset_id,
                dataset_hash(examples),
                report["calibration"]["svm_temperature"],
                report["calibration"]["ensemble_temperature"],
                policy["confidence_threshold"],
                policy["min_margin"],
                int(policy["disagreement_abstain"]),
                policy["target_precision"],
                int(policy["low_reliability"]),
                sklearn_version,
            ),
        )
    return {
        **report,
        "training_dataset_id": request.training_dataset_id,
        "training_dataset_name": dataset_name,
        "calibration_saved": True,
        "decision_policy": {
            "confidence_threshold": policy["confidence_threshold"],
            "min_margin": policy["min_margin"],
            "disagreement_abstain": policy["disagreement_abstain"],
        },
    }


@router.get("/api/training-datasets/{dataset_id}/topics")
def list_training_topics(dataset_id: str) -> dict:
    if dataset_id == "builtin":
        return {"topics": BUILTIN_TRAINING_TOPICS}
    with connect() as db:
        dataset = db.execute(
            "SELECT id FROM training_datasets WHERE id=?", (dataset_id,)
        ).fetchone()
        if not dataset:
            raise HTTPException(status_code=404, detail="Training dataset not found.")
        rows = db.execute(
            "SELECT DISTINCT topic FROM training_examples "
            "WHERE dataset_id=? ORDER BY topic COLLATE NOCASE",
            (dataset_id,),
        ).fetchall()
    return {"topics": [row["topic"] for row in rows]}


def _validate_training_examples(examples: list[tuple[str, str]]) -> None:
    if not examples:
        raise HTTPException(status_code=422, detail="The dataset contains no labeled examples.")
    topics = {topic.strip() for _, topic in examples if topic.strip()}
    if any(not text.strip() or not topic.strip() for text, topic in examples):
        raise HTTPException(
            status_code=422,
            detail="Every training row needs non-empty text and a topic label.",
        )
    if len(topics) < 2:
        raise HTTPException(
            status_code=422,
            detail="Training data must contain at least two different topic labels.",
        )


def _save_training_dataset(
    name: str,
    source_type: str,
    examples: list[tuple[str, str]],
    example_sources: list[dict | None] | None = None,
) -> dict:
    dataset_id = str(uuid.uuid4())
    with connect() as db:
        db.execute(
            "INSERT INTO training_datasets(id, name, source_type) VALUES(?, ?, ?)",
            (dataset_id, name, source_type),
        )
        db.executemany(
            "INSERT INTO training_examples("
            "id, dataset_id, topic, text, source_material_id, source_material_name, source_reference"
            ") VALUES(?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    str(uuid.uuid4()), dataset_id, topic.strip(), text.strip(),
                    (example_sources[index] or {}).get("id") if example_sources else None,
                    (example_sources[index] or {}).get("name") if example_sources else None,
                    "Labeled uploaded course material" if example_sources else None,
                )
                for index, (text, topic) in enumerate(examples)
            ],
        )
    return {
        "id": dataset_id,
        "name": name,
        "source_type": source_type,
        "example_count": len(examples),
        "topic_count": len({topic.strip() for _, topic in examples}),
    }


@router.post("/api/training-datasets/csv")
async def import_training_csv(
    file: UploadFile = File(...),
    name: str | None = Form(default=None, max_length=100),
) -> dict:
    filename = Path((file.filename or "training-data.csv").replace("\\", "/")).name
    if Path(filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=415, detail="Choose a CSV training dataset.")
    content = await read_limited(file, MAX_UPLOAD_BYTES)
    def import_dataset() -> dict:
        try:
            examples, detected = read_labeled_csv(content)
        except CsvImportError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
        _validate_training_examples(examples)
        dataset_name = (name or "").strip() or Path(filename).stem.strip()
        if not dataset_name:
            raise HTTPException(status_code=422, detail="Enter a name for this dataset.")
        dataset = _main._save_training_dataset(dataset_name, "csv", examples)
        return {**dataset, "detected": detected}

    return await run_in_threadpool(import_dataset)


@router.post("/api/training-datasets/documents")
def create_document_dataset(request: DocumentDatasetRequest) -> dict:
    dataset_name = request.name.strip()
    if not dataset_name:
        raise HTTPException(status_code=422, detail="Enter a name for this dataset.")
    if len({example.upload_id for example in request.examples}) != len(request.examples):
        raise HTTPException(status_code=422, detail="Select each document only once.")
    topics = {example.topic.strip() for example in request.examples if example.topic.strip()}
    if len(topics) < 2:
        raise HTTPException(
            status_code=422,
            detail="Assign at least two different topic labels to your documents.",
        )
    examples = []
    example_sources = []
    with connect() as db:
        for item in request.examples:
            row = db.execute(
                "SELECT name, stored_path FROM uploads WHERE id=?", (item.upload_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="A selected document was not found.")
            path = Path(row["stored_path"]).resolve()
            if path.parent != _main.UPLOADS.resolve():
                raise HTTPException(status_code=500, detail="Stored upload path is invalid.")
            try:
                text = _main.extract_text(row["name"], path.read_bytes())
            except OSError as error:
                raise HTTPException(
                    status_code=500, detail=f"Could not read {row['name']}: {error}"
                ) from error
            examples.append((text, item.topic))
            example_sources.append({"id": item.upload_id, "name": row["name"]})
    _validate_training_examples(examples)
    return _main._save_training_dataset(dataset_name, "documents", examples, example_sources)


@router.delete("/api/training-datasets/{dataset_id}")
def delete_training_dataset(dataset_id: str) -> dict:
    if dataset_id == "builtin":
        raise HTTPException(status_code=409, detail="Built-in examples cannot be deleted.")
    with connect() as db:
        db.execute(
            "DELETE FROM model_calibration WHERE dataset_id=?",
            (dataset_id,),
        )
        cursor = db.execute("DELETE FROM training_datasets WHERE id=?", (dataset_id,))
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Training dataset not found.")
    return {"deleted": dataset_id}
