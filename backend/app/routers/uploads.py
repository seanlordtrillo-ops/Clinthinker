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
from ..questions import *
from ..schemas import *
from ..services.updates import *
from ..services.uploads import _is_exam_upload

from app import main as _main

router = APIRouter()


def _store_upload(name: str, content: bytes, deduplicate: bool = False) -> dict:
    text = _main.extract_text(name, content)
    if deduplicate:
        with connect() as db:
            candidates = db.execute(
                "SELECT id, name, stored_path, bytes, text_chars, uploaded_at "
                "FROM uploads WHERE bytes=? ORDER BY uploaded_at DESC",
                (len(content),),
            ).fetchall()
        for candidate in candidates:
            path = Path(candidate["stored_path"]).resolve()
            if path.parent == _main.UPLOADS.resolve() and path.is_file():
                if path.read_bytes() == content:
                    return {
                        "id": candidate["id"],
                        "name": candidate["name"],
                        "bytes": candidate["bytes"],
                        "text_chars": candidate["text_chars"],
                        "text": text,
                        "duplicate": True,
                    }
    upload_id = str(uuid.uuid4())
    destination = _main.UPLOADS / f"{upload_id}{Path(name).suffix.lower()}"
    destination.write_bytes(content)
    try:
        with connect() as db:
            db.execute(
                "INSERT INTO uploads(id, name, stored_path, bytes, text_chars) "
                "VALUES(?, ?, ?, ?, ?)",
                (upload_id, name, str(destination), len(content), len(text)),
            )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return {
        "id": upload_id,
        "name": name,
        "bytes": len(content),
        "text_chars": len(text),
        "text": text,
        "duplicate": False,
    }


async def _receive_upload(file: UploadFile, deduplicate: bool = False) -> dict:
    content = await read_limited(file)
    name = Path((file.filename or "upload").replace("\\", "/")).name
    return await run_in_threadpool(_store_upload, name, content, deduplicate)


@checks(
    expected="Uploaded file metadata",
    probable_cause="Upload parsing or storage failed",
)
@router.post("/api/upload")
async def upload_material(file: UploadFile = File(...)) -> dict:
    return await _receive_upload(file)


@router.post("/api/lessons/upload")
async def upload_lesson(file: UploadFile = File(...)) -> dict:
    lesson = await _receive_upload(file, deduplicate=True)
    lesson.pop("text")
    return lesson


@router.get("/api/uploads")
def list_uploads() -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT id, name, bytes, text_chars, uploaded_at, is_exam FROM uploads "
            "ORDER BY uploaded_at DESC"
        ).fetchall()
    return [
        {
            **dict(row),
            "is_exam": None if row["is_exam"] is None else bool(row["is_exam"]),
            "exam_auto": _is_exam_upload({"is_exam": None, "name": row["name"]}),
        }
        for row in rows
    ]


@router.put("/api/uploads/{upload_id}/exam")
def update_upload_exam(upload_id: str, request: UploadExamUpdate) -> dict:
    with connect() as db:
        cursor = db.execute(
            "UPDATE uploads SET is_exam=? WHERE id=?",
            (int(request.is_exam), upload_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Uploaded file not found.")
    return {"id": upload_id, "is_exam": request.is_exam}


@router.get("/api/uploads/{upload_id}/text")
def read_uploaded_text(upload_id: str) -> dict:
    with connect() as db:
        row = db.execute(
            "SELECT name, stored_path FROM uploads WHERE id=?", (upload_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Uploaded file not found.")
    path = Path(row["stored_path"]).resolve()
    if path.parent != _main.UPLOADS.resolve():
        raise HTTPException(status_code=500, detail="Stored upload path is invalid.")
    try:
        text = _main.extract_text(row["name"], path.read_bytes())
    except OSError as error:
        raise HTTPException(
            status_code=500, detail=f"Could not read saved upload: {error}"
        ) from error
    return {"id": upload_id, "name": row["name"], "text": text}


@router.delete("/api/uploads/{upload_id}")
def delete_upload(upload_id: str) -> dict:
    with connect() as db:
        row = db.execute(
            "SELECT stored_path FROM uploads WHERE id=?", (upload_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Uploaded file not found.")
        path = Path(row["stored_path"]).resolve()
        if path.parent != _main.UPLOADS.resolve():
            raise HTTPException(status_code=500, detail="Stored upload path is invalid.")
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise HTTPException(
                status_code=500, detail=f"Could not delete upload: {error}"
            ) from error
        db.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
    return {"deleted": upload_id}
