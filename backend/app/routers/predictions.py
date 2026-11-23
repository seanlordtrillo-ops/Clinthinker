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
from ..ml import classify_with_policy, get_decision_policy, predict
from ..parsing import MAX_UPLOAD_BYTES, extract_lesson_features, extract_text, read_limited
from ..questions import *
from ..schemas import *
from ..services.updates import *

import importlib

def _compat_main():
    return importlib.import_module("app.main")

router = APIRouter()


@checks(
    expected="Prediction analysis result",
    probable_cause="Prediction or dataset analysis failed",
)
def _analyze(request: PredictionRequest, progress_callback=None) -> dict:
    dataset_id = request.training_dataset_id
    if dataset_id == "builtin":
        dataset_name = "Built-in examples"
        training_examples = None
    else:
        with connect() as db:
            dataset = db.execute(
                "SELECT name FROM training_datasets WHERE id=?", (dataset_id,)
            ).fetchone()
            if not dataset:
                raise HTTPException(status_code=404, detail="Training dataset not found.")
            rows = db.execute(
                "SELECT text, topic FROM training_examples "
                "WHERE dataset_id=? ORDER BY rowid",
                (dataset_id,),
            ).fetchall()
        training_examples = [(row["text"], row["topic"]) for row in rows]
        dataset_name = dataset["name"]
    predictions = predict(
        request.text,
        training_examples=training_examples,
        progress_callback=progress_callback,
    )
    decision_policy = get_decision_policy(
        {"id": dataset_id, "examples": (
            BUILTIN_TRAINING_EXAMPLES if training_examples is None else training_examples
        )}
    )
    classification = classify_with_policy(
        request.text,
        training_examples=training_examples,
        dataset_id=dataset_id,
        decision_policy=decision_policy,
    )
    predictions = [
        {
            **prediction,
            "margin": classification["margin"],
            "models_agree": classification["models_agree"],
            "abstain_reason": classification["abstain_reason"],
        }
        for prediction in predictions
    ]
    analysis_id = str(uuid.uuid4())
    with connect() as db:
        db.execute(
            "INSERT INTO analyses("
            "id, source_label, predictions, method, training_dataset_id, "
            "training_dataset_name) VALUES(?, ?, ?, ?, ?, ?)",
            (
                analysis_id,
                "Uploaded materials",
                json.dumps(predictions),
                PREDICTION_METHOD,
                dataset_id,
                dataset_name,
            ),
        )
    return {
        "id": analysis_id,
        "label": "Uploaded materials",
        "method": PREDICTION_METHOD,
        "training_dataset_id": dataset_id,
        "training_dataset_name": dataset_name,
        "predictions": predictions,
        **classification,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/api/predict/stream")
async def predict_stream(request: PredictionRequest) -> StreamingResponse:
    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Course material text is required.")

    async def events():
        loop = asyncio.get_running_loop()
        updates: asyncio.Queue[dict] = asyncio.Queue()

        def report(update: dict) -> None:
            loop.call_soon_threadsafe(updates.put_nowait, update)

        task = asyncio.create_task(run_in_threadpool(_compat_main()._analyze, request, report))
        try:
            while not task.done() or not updates.empty():
                try:
                    update = await asyncio.wait_for(updates.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
                yield f"event: progress\ndata: {json.dumps(update)}\n\n"
            result = await task
        except (ValueError, HTTPException) as error:
            message = error.detail if isinstance(error, HTTPException) else str(error)
            yield f"event: error\ndata: {json.dumps({'detail': message})}\n\n"
            return
        except Exception:
            yield (
                "event: error\n"
                f"data: {json.dumps({'detail': 'Analysis failed. Please try again.'})}\n\n"
            )
            return
        yield f"event: result\ndata: {json.dumps(result)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/analysis/latest")
def latest_analysis() -> dict | None:
    with connect() as db:
        row = db.execute(
            "SELECT id, source_label, predictions, method, training_dataset_id, "
            "training_dataset_name, created_at FROM analyses "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "label": row["source_label"],
        "method": row["method"],
        "training_dataset_id": row["training_dataset_id"],
        "training_dataset_name": row["training_dataset_name"],
        "predictions": json.loads(row["predictions"]),
        "created_at": row["created_at"],
    }
