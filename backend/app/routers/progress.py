"""Routes for answering questions, study progress and spaced review."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import progress
from ..schemas import SubmitAnswerRequest
from .questions import _QUESTION_BATCH_UNAVAILABLE_DETAIL, _question_batches

router = APIRouter()


def _find_question(request: SubmitAnswerRequest) -> dict:
    """Look in the current practice set first, then Saved Questions, then past answers."""
    if request.generation_id:
        batch = _question_batches.get(request.generation_id)
        if batch:
            for item in batch["result"]["questions"]:
                if item["id"] == request.question_id:
                    return item
    question = progress.find_saved_question(request.question_id) or progress.find_practice_item(
        request.question_id
    )
    if question:
        return question
    if request.generation_id and request.generation_id not in _question_batches:
        raise HTTPException(status_code=410, detail=_QUESTION_BATCH_UNAVAILABLE_DETAIL)
    raise HTTPException(status_code=404, detail="Question not found.")


@router.post("/api/attempts")
def submit_answer(request: SubmitAnswerRequest) -> dict:
    """Check one answer on the server, save it, and schedule the next review."""
    return progress.record_attempt(_find_question(request), request.answer)


@router.get("/api/progress")
def read_progress() -> dict:
    return progress.progress_summary()


@router.delete("/api/progress")
def clear_progress() -> dict:
    return progress.reset_progress()


@router.get("/api/review/due")
def read_due_reviews(limit: int = 20, topic: str | None = None, mistakes_only: bool = False) -> dict:
    return progress.due_reviews(limit=limit, topic=topic, mistakes_only=mistakes_only)
