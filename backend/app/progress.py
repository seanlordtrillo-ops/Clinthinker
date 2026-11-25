"""Study progress: answer checking, topic mastery, study priority and spaced review.

How it works, in plain terms:
- Every submitted answer is checked here (never in the browser) and saved as an attempt.
- Mastery of a topic = smoothed, recency-weighted share of correct answers.
- Study priority = exam likelihood of the topic x (1 - mastery).
- Spaced repetition uses five Leitner boxes: a wrong answer goes back to box 1
  (review now); a correct answer moves the question up one box (review later).
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

from fastapi import HTTPException

from .core.checks import checks
from .database import connect

# Days to wait before a question comes back, by Leitner box.
LEITNER_INTERVAL_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 14}
# Only the most recent answers per topic count toward mastery.
RECENT_ATTEMPTS = 10
# Each older answer counts 85% as much as the one after it.
RECENCY_DECAY = 0.85
# Mastery is shown as "measured" only after this many answers.
MIN_MEASURED_ATTEMPTS = 3
# Used when a topic has no likelihood yet (for example, course-material mode).
UNKNOWN_LIKELIHOOD = 0.5
UNCLASSIFIED = "Unclassified"
MAX_RECOMMENDATIONS = 3
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _now(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


def _stamp(moment: datetime) -> str:
    # Same text format as SQLite's datetime('now'), so stored times compare correctly.
    return moment.astimezone(timezone.utc).strftime(_TIME_FORMAT)


def _likelihood_label(score: float) -> str:
    if score >= 0.67:
        return "High"
    if score >= 0.34:
        return "Medium"
    return "Low"


def normalize_answer(text: str) -> str:
    """Lowercase, trim, collapse spaces and drop surrounding punctuation."""
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip().casefold()
    return cleaned.strip(" .,;:!?\"'()[]")


def is_correct_answer(question_type: str, chosen: str, correct: str) -> bool:
    return normalize_answer(chosen) == normalize_answer(correct)


def validate_answer_format(question: Mapping, answer: str) -> str:
    """Reject answers that are impossible for the question type; return the clean answer."""
    answer = str(answer or "").strip()
    if not answer:
        raise HTTPException(status_code=422, detail="Enter an answer first.")
    question_type = question.get("question_type")
    if question_type == "True or False":
        if normalize_answer(answer) not in {"true", "false"}:
            raise HTTPException(status_code=422, detail="Answer True or False.")
        return "True" if normalize_answer(answer) == "true" else "False"
    if question_type == "Multiple Choice":
        choices = list(question.get("choices") or [])
        match = next(
            (choice for choice in choices if normalize_answer(choice) == normalize_answer(answer)),
            None,
        )
        if match is None:
            raise HTTPException(status_code=422, detail="Choose one of the listed answers.")
        return match
    return answer


def _decay_weights(count: int) -> list[float]:
    # Newest answer first: 1, 0.85, 0.72, ...
    return [RECENCY_DECAY ** index for index in range(count)]


def mastery_from_results(results_newest_first: Iterable[int]) -> dict:
    """Recency-weighted share correct, with add-one smoothing.

    With no answers the estimate is 0.5 (unknown). Each answer pulls it toward
    what the user actually got, newer answers more than older ones.
    """
    recent = [1 if result else 0 for result in results_newest_first][:RECENT_ATTEMPTS]
    weights = _decay_weights(len(recent))
    weighted_correct = sum(weight * result for weight, result in zip(weights, recent))
    total_weight = sum(weights)
    estimate = (weighted_correct + 1.0) / (total_weight + 2.0)
    return {
        "mastery": round(estimate, 4),
        "mastery_measured": len(recent) >= MIN_MEASURED_ATTEMPTS,
        "recent_attempts_used": len(recent),
    }


def study_priority(likelihood_score: float | None, mastery: float) -> float:
    likelihood = UNKNOWN_LIKELIHOOD if likelihood_score is None else likelihood_score
    likelihood = max(0.0, min(1.0, float(likelihood)))
    return round(likelihood * (1.0 - max(0.0, min(1.0, mastery))), 4)


def next_box(current_box: int | None, correct: bool) -> int:
    if not correct:
        return 1
    return min(5, (current_box or 1) + 1)


def _save_practice_item(db, question: Mapping, moment: datetime) -> None:
    db.execute(
        "INSERT INTO practice_items("
        "question_id, question_text, question_type, topic, difficulty, choices, "
        "correct_answer, explanation, source_material_id, source_material_name, "
        "likelihood_score, first_seen_at"
        ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(question_id) DO UPDATE SET "
        "likelihood_score=COALESCE(excluded.likelihood_score, practice_items.likelihood_score)",
        (
            question["id"],
            question["question_text"],
            question["question_type"],
            question.get("topic") or UNCLASSIFIED,
            question.get("difficulty") or "Moderate",
            json.dumps(list(question.get("choices") or [])),
            question["correct_answer"],
            question.get("support_excerpt") or question.get("explanation") or "",
            question.get("source_material_id"),
            question.get("source_material_name") or "",
            question.get("likelihood_score"),
            _stamp(moment),
        ),
    )


def _topic_history(db, topic: str) -> list[int]:
    return [
        row["correct"]
        for row in db.execute(
            "SELECT correct FROM attempts WHERE topic=? "
            "ORDER BY answered_at DESC, rowid DESC LIMIT ?",
            (topic, RECENT_ATTEMPTS),
        ).fetchall()
    ]


@checks(
    expected="Saved answer with result",
    probable_cause="The answer could not be checked or saved",
)
def record_attempt(
    question: Mapping,
    answer: str,
    *,
    source: str = "practice",
    student_name: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Check one answer, save it, and move the question to its next review box."""
    moment = _now(now)
    chosen = validate_answer_format(question, answer)
    correct = is_correct_answer(question["question_type"], chosen, question["correct_answer"])
    topic = question.get("topic") or UNCLASSIFIED
    with connect() as db:
        _save_practice_item(db, question, moment)
        db.execute(
            "INSERT INTO attempts("
            "id, question_id, topic, source_material_id, chosen_answer, correct, "
            "source, student_name, answered_at"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                question["id"],
                topic,
                question.get("source_material_id"),
                chosen,
                int(correct),
                source,
                student_name,
                _stamp(moment),
            ),
        )
        current = db.execute(
            "SELECT box FROM review_schedule WHERE question_id=?", (question["id"],)
        ).fetchone()
        box = next_box(current["box"] if current else None, correct)
        due_at = moment + timedelta(days=LEITNER_INTERVAL_DAYS[box])
        db.execute(
            "INSERT INTO review_schedule(question_id, box, due_at, last_correct, updated_at) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(question_id) DO UPDATE SET box=excluded.box, "
            "due_at=excluded.due_at, last_correct=excluded.last_correct, "
            "updated_at=excluded.updated_at",
            (question["id"], box, _stamp(due_at), int(correct), _stamp(moment)),
        )
        history = _topic_history(db, topic)
    return {
        "question_id": question["id"],
        "correct": correct,
        "your_answer": chosen,
        "correct_answer": question["correct_answer"],
        "explanation": question.get("support_excerpt") or question.get("explanation") or "",
        "topic": topic,
        "review_box": box,
        "next_review_at": _stamp(due_at),
        "topic_mastery": mastery_from_results(history),
    }


def find_practice_item(question_id: str) -> dict | None:
    """A question the user answered before (used when reviewing)."""
    with connect() as db:
        row = db.execute(
            "SELECT * FROM practice_items WHERE question_id=?", (question_id,)
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["id"] = item.pop("question_id")
    item["choices"] = json.loads(item["choices"])
    return item


def find_saved_question(question_id: str) -> dict | None:
    """A question from Saved Questions."""
    with connect() as db:
        row = db.execute(
            "SELECT id, question_text, question_type, topic, difficulty, choices, "
            "correct_answer, support_excerpt, source_material_id, source_material_name "
            "FROM generated_questions WHERE id=?",
            (question_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["choices"] = json.loads(item["choices"])
    if not item.get("support_excerpt"):
        item.pop("support_excerpt", None)
    return item


def record_topic_likelihood(
    lesson_ids: Iterable[str],
    likely_topics: Iterable[Mapping],
    *,
    now: datetime | None = None,
) -> int:
    """Remember the newest likelihood of each topic for each lesson."""
    moment = _stamp(_now(now))
    lesson_ids = list(dict.fromkeys(lesson_ids))
    likely_topics = list(likely_topics)
    rows = []
    for lesson_id in lesson_ids:
        for item in likely_topics:
            topic = str(item.get("topic") or "").strip()
            if not topic:
                continue
            score = max(0.0, min(1.0, float(item.get("likelihood_score") or 0.0)))
            rows.append(
                (lesson_id, topic, score, item.get("likelihood") or _likelihood_label(score), moment)
            )
    if not rows:
        return 0
    with connect() as db:
        existing = {
            row["id"]
            for row in db.execute(
                f"SELECT id FROM uploads WHERE id IN ({','.join('?' for _ in lesson_ids)})",
                tuple(lesson_ids),
            ).fetchall()
        }
        rows = [row for row in rows if row[0] in existing]
        db.executemany(
            "INSERT INTO topic_likelihood(upload_id, topic, likelihood_score, likelihood, updated_at) "
            "VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(upload_id, topic) DO UPDATE SET "
            "likelihood_score=excluded.likelihood_score, likelihood=excluded.likelihood, "
            "updated_at=excluded.updated_at",
            rows,
        )
    return len(rows)


def _recommendation_reason(topic: dict) -> str:
    likelihood = (
        f"{topic['likelihood']} exam likelihood"
        if topic["likelihood_score"] is not None
        else "Exam likelihood not ranked yet"
    )
    if topic["attempts"] == 0:
        practice = "not practiced yet"
    else:
        practice = (
            f"{round(topic['mastery'] * 100)}% mastery from "
            f"{topic['attempts']} answer{'s' if topic['attempts'] != 1 else ''}"
        )
    due = (
        f" · {topic['due_reviews']} question{'s' if topic['due_reviews'] != 1 else ''} due for review"
        if topic["due_reviews"]
        else ""
    )
    return f"{likelihood} · {practice}{due}"


@checks(
    expected="Study progress summary",
    probable_cause="Study progress could not be calculated",
)
def progress_summary(*, now: datetime | None = None) -> dict:
    """Per-topic mastery and priority, plus the top topics to study next."""
    moment = _stamp(_now(now))
    with connect() as db:
        likelihood_rows = db.execute(
            "SELECT topic, MAX(likelihood_score) AS likelihood_score "
            "FROM topic_likelihood GROUP BY topic"
        ).fetchall()
        attempt_rows = db.execute(
            "SELECT topic, correct, answered_at FROM attempts "
            "ORDER BY answered_at DESC, rowid DESC"
        ).fetchall()
        due_rows = db.execute(
            "SELECT p.topic, COUNT(*) AS due FROM review_schedule r "
            "JOIN practice_items p ON p.question_id=r.question_id "
            "WHERE r.due_at <= ? GROUP BY p.topic",
            (moment,),
        ).fetchall()
        tracked_rows = db.execute(
            "SELECT topic, COUNT(*) AS tracked FROM practice_items GROUP BY topic"
        ).fetchall()

    likelihood_by_topic = {row["topic"]: row["likelihood_score"] for row in likelihood_rows}
    due_by_topic = {row["topic"]: row["due"] for row in due_rows}
    tracked_by_topic = {row["topic"]: row["tracked"] for row in tracked_rows}
    history: dict[str, list[int]] = {}
    totals_by_topic: dict[str, list[int]] = {}
    last_attempt: dict[str, str] = {}
    for row in attempt_rows:
        history.setdefault(row["topic"], []).append(row["correct"])
        totals = totals_by_topic.setdefault(row["topic"], [0, 0])
        totals[0] += 1
        totals[1] += row["correct"]
        last_attempt.setdefault(row["topic"], row["answered_at"])

    topics = []
    for topic in sorted(set(likelihood_by_topic) | set(history), key=str.casefold):
        mastery = mastery_from_results(history.get(topic, []))
        likelihood_score = likelihood_by_topic.get(topic)
        attempts, correct = totals_by_topic.get(topic, [0, 0])
        topics.append(
            {
                "topic": topic,
                "likelihood_score": (
                    round(likelihood_score, 4) if likelihood_score is not None else None
                ),
                "likelihood": (
                    _likelihood_label(likelihood_score) if likelihood_score is not None else "Unknown"
                ),
                "mastery": mastery["mastery"],
                "mastery_measured": mastery["mastery_measured"],
                "attempts": attempts,
                "correct": correct,
                "last_attempt_at": last_attempt.get(topic),
                "due_reviews": due_by_topic.get(topic, 0),
                "tracked_questions": tracked_by_topic.get(topic, 0),
                "priority": study_priority(likelihood_score, mastery["mastery"]),
            }
        )
    topics.sort(key=lambda item: (-item["priority"], item["topic"].casefold()))

    recommendations = [
        {**topic, "reason": _recommendation_reason(topic)}
        for topic in topics
        if topic["topic"] != UNCLASSIFIED and topic["priority"] > 0
    ][:MAX_RECOMMENDATIONS]

    total_attempts = sum(item["attempts"] for item in topics)
    total_correct = sum(item["correct"] for item in topics)
    return {
        "topics": topics,
        "recommendations": recommendations,
        "totals": {
            "attempts": total_attempts,
            "correct": total_correct,
            "accuracy": round(total_correct / total_attempts, 4) if total_attempts else None,
            "topics_practiced": sum(1 for item in topics if item["attempts"]),
            "due_now": sum(due_by_topic.values()),
            "tracked_questions": sum(tracked_by_topic.values()),
        },
        "method": {
            "mastery": (
                f"Share of correct answers in the last {RECENT_ATTEMPTS} answers per topic, "
                f"newer answers weighted more (each older answer counts {RECENCY_DECAY:.0%} "
                "of the next), with add-one smoothing so a new topic starts at 50%."
            ),
            "mastery_measured_after": MIN_MEASURED_ATTEMPTS,
            "priority": "exam likelihood × (1 − mastery); unknown likelihood counts as 0.5",
            "review_intervals_days": {str(box): days for box, days in LEITNER_INTERVAL_DAYS.items()},
        },
        "generated_at": moment,
    }


@checks(
    expected="Questions due for review",
    probable_cause="Review questions could not be loaded",
)
def due_reviews(
    *,
    limit: int = 20,
    topic: str | None = None,
    mistakes_only: bool = False,
    now: datetime | None = None,
) -> dict:
    """Questions whose review time has come, oldest first. Answers are not included."""
    if not 1 <= int(limit) <= 50:
        raise HTTPException(status_code=422, detail="Choose between 1 and 50 questions.")
    moment = _stamp(_now(now))
    conditions = ["r.due_at <= ?"]
    parameters: list = [moment]
    if topic:
        conditions.append("p.topic = ?")
        parameters.append(topic)
    if mistakes_only:
        conditions.append("r.last_correct = 0")
    where = " AND ".join(conditions)
    with connect() as db:
        due_now = db.execute(
            "SELECT COUNT(*) FROM review_schedule r "
            "JOIN practice_items p ON p.question_id=r.question_id "
            f"WHERE {where}",
            tuple(parameters),
        ).fetchone()[0]
        rows = db.execute(
            "SELECT p.question_id, p.question_text, p.question_type, p.topic, p.difficulty, "
            "p.choices, p.source_material_name, r.box, r.due_at, r.last_correct "
            "FROM review_schedule r JOIN practice_items p ON p.question_id=r.question_id "
            f"WHERE {where} ORDER BY r.box, r.due_at, p.rowid LIMIT ?",
            (*parameters, int(limit)),
        ).fetchall()
    questions = []
    for row in rows:
        item = dict(row)
        item["choices"] = json.loads(item["choices"])
        item["last_correct"] = bool(item["last_correct"])
        questions.append(item)
    return {"due_now": due_now, "returned": len(questions), "questions": questions}


@checks(
    expected="Study progress cleared",
    probable_cause="Study progress could not be cleared",
)
def reset_progress() -> dict:
    with connect() as db:
        attempts = db.execute("DELETE FROM attempts").rowcount
        db.execute("DELETE FROM review_schedule")
        items = db.execute("DELETE FROM practice_items").rowcount
    return {"attempts_deleted": attempts, "questions_deleted": items}
