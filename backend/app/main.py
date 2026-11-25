from __future__ import annotations

import os
import sys
import tempfile
import subprocess
import hashlib
import time
import threading
import urllib.error
import urllib.request
from collections import OrderedDict
from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import database
from .database import UPLOADS, connect, get_settings, initialize, save_settings
from .core import logging_setup as _core_logging_setup
from .core.checks import checks
from .core.security import LocalRequestGuard

from .schemas import (
    DocumentDatasetRequest, EvaluateDatasetRequest, GenerateQuestionsRequest,
    LabeledUpload, PredictionRequest, PriorityWeights, QuestionFeedbackRequest,
    QuestionGenerationSettings, RenameSavedSessionRequest, ResetQuestionHistoryRequest,
    SaveQuestionsRequest, SettingsUpdate, UploadExamUpdate,
)
from .services.updates import (
    UPDATE_MANIFEST_URL, _download_update_asset, _fetch_update_manifest,
    _github_asset_api_url, update_failure_cause, _valid_installer_url,
    _valid_sha256, _version_parts,
)
from .ml import (
    BUILTIN_TRAINING_EXAMPLES,
    BUILTIN_TRAINING_TOPICS,
    augment_training_examples_with_exam_passages,
    classify_with_policy,
    get_decision_policy,
    predict,
)
from .parsing import extract_lesson_features, extract_text, read_limited
from .questions import (
    extract_exam_question_patterns,
    generate_questions,
    question_preference_features,
    rank_lesson_likelihood,
)

APP_NAME = "Clinthinker©"
APP_VERSION = "2.0.6"
_logging_setup_complete = False
app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:4173", "http://127.0.0.1:4173"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)
# Added last so it runs first: refuse other websites and unknown host names.
app.add_middleware(LocalRequestGuard)

_bundled_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
WEB_DIR = Path(
    os.environ.get(
        "TOPIC_ASSISTANT_WEB_DIR",
        _bundled_root / "frontend_dist"
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[2] / "frontend" / "dist",
    )
)

@app.on_event("startup")
def startup() -> None:
    global _logging_setup_complete
    if not _logging_setup_complete:
        _core_logging_setup.setup_logging()
        _logging_setup_complete = True
    initialize()

from .routers.system import router as system_router
from .routers.updates import router as updates_router
from .routers.uploads import router as uploads_router
from .routers.datasets import router as datasets_router
from .routers.predictions import router as predictions_router
from .routers.questions import router as questions_router
from .routers.settings import router as settings_router
from .routers.progress import router as progress_router
from .routers.assessments import router as assessments_router
from .routers.classroom import router as classroom_router

app.router.routes.extend(system_router.routes)
app.router.routes.extend(updates_router.routes)
app.router.routes.extend(uploads_router.routes)
app.router.routes.extend(datasets_router.routes)
app.router.routes.extend(predictions_router.routes)
app.router.routes.extend(questions_router.routes)
app.router.routes.extend(settings_router.routes)
app.router.routes.extend(progress_router.routes)
app.router.routes.extend(assessments_router.routes)
app.router.routes.extend(classroom_router.routes)

if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="frontend")


# Compatibility exports for existing imports and patches.
# The HTTP routes log errors through @checks on their implementations; the checked
# wrappers at the bottom of this file call the unlogged versions, so each error is
# logged once either way.
from .routers.system import health as health
from .routers.system import diagnostics as diagnostics
from .routers.system import database_recent_question_topics as database_recent_question_topics
from .routers.updates import check_for_updates as check_for_updates
from .routers.updates import _log_update_stage as _log_update_stage
from .routers.updates import _update_http_failure_cause as _update_http_failure_cause
from .routers.updates import _raise_update_stage_failure as _raise_update_stage_failure
from .routers.updates import install_update as install_update
from .routers.uploads import _store_upload as _store_upload
from .routers.uploads import _receive_upload as _receive_upload
from .routers.uploads import upload_material as upload_material
from .routers.uploads import upload_lesson as upload_lesson
from .routers.uploads import list_uploads as list_uploads
from .routers.uploads import _is_exam_upload as _is_exam_upload
from .routers.uploads import update_upload_exam as update_upload_exam
from .routers.uploads import read_uploaded_text as read_uploaded_text
from .routers.uploads import delete_upload as delete_upload
from .routers.datasets import list_training_datasets as list_training_datasets
from .routers.datasets import evaluate_training_dataset as evaluate_training_dataset
from .routers.datasets import list_training_topics as list_training_topics
from .routers.datasets import _validate_training_examples as _validate_training_examples
from .routers.datasets import _save_training_dataset as _save_training_dataset
from .routers.datasets import import_training_csv as import_training_csv
from .routers.datasets import create_document_dataset as create_document_dataset
from .routers.datasets import delete_training_dataset as delete_training_dataset
from .routers.predictions import _analyze as _analyze
from .routers.predictions import predict_stream as predict_stream
from .routers.predictions import latest_analysis as latest_analysis
from .routers.questions import generate_practice_questions as generate_practice_questions
from .routers.questions import get_question_preferences as get_question_preferences
from .routers.questions import save_question_feedback as save_question_feedback
from .routers.questions import clear_question_feedback as clear_question_feedback
from .routers.questions import reset_question_history as reset_question_history
from .routers.questions import reveal_question_answers as reveal_question_answers
from .routers.questions import save_practice_questions as save_practice_questions
from .routers.questions import list_saved_questions as list_saved_questions
from .routers.questions import rename_saved_session as rename_saved_session
from .routers.questions import delete_saved_session as delete_saved_session
from .routers.settings import read_settings as read_settings
from .routers.settings import update_settings as update_settings
from .routers.progress import submit_answer as submit_answer
from .routers.progress import read_progress as read_progress
from .routers.progress import clear_progress as clear_progress
from .routers.progress import read_due_reviews as read_due_reviews
from .routers.assessments import build_test as build_test
from .routers.assessments import list_tests as list_tests
from .routers.assessments import read_test as read_test
from .routers.assessments import rename_test as rename_test
from .routers.assessments import delete_test as delete_test
from .routers.assessments import export_test as export_test
from .routers.assessments import results_template as results_template
from .routers.assessments import import_results as import_results
from .routers.assessments import read_analysis as read_analysis
from .routers.classroom import read_classroom as read_classroom
from .routers.classroom import start_classroom as start_classroom
from .routers.classroom import end_classroom as end_classroom
from .routers.questions import _question_batches as _question_batches
from .routers.questions import _MAX_QUESTION_BATCHES as _MAX_QUESTION_BATCHES
from .routers.questions import _QUESTION_BATCH_UNAVAILABLE_DETAIL as _QUESTION_BATCH_UNAVAILABLE_DETAIL


@checks(
    expected="Prediction analysis result",
    probable_cause="Prediction or dataset analysis failed",
)
def _analyze(request: PredictionRequest, progress_callback=None) -> dict:
    from .routers import predictions as predictions_module
    return predictions_module._analyze(request, progress_callback)


@checks(
    expected="Generated question result",
    probable_cause="Question generation failed",
)
def generate_practice_questions(request: GenerateQuestionsRequest) -> dict:
    from .routers import questions as questions_module
    # Call the unlogged implementation so an error is logged once, here.
    return questions_module._generate_practice_questions.__wrapped__(request)


@checks(
    expected="Saved practice questions",
    probable_cause="Saving practice questions failed",
)
def save_practice_questions(request: SaveQuestionsRequest) -> dict:
    from .routers import questions as questions_module
    return questions_module._save_practice_questions.__wrapped__(request)


@checks(
    expected="Uploaded file metadata",
    probable_cause="Upload parsing or storage failed",
)
async def upload_material(file: UploadFile = File(...)) -> dict:
    from .routers import uploads as uploads_module
    return await uploads_module._upload_material.__wrapped__(file)
