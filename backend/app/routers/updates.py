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
from ..services.updates import (
    UPDATE_MANIFEST_URL,
    _download_update_asset,
    _fetch_update_manifest,
    _github_asset_api_url,
    update_failure_cause,
    _valid_installer_url,
    _valid_sha256,
    _version_parts,
)

from app import main as _main

router = APIRouter()

APP_VERSION = "2.0.5"


@router.get("/api/updates/check")
def check_for_updates() -> dict:
    try:
        manifest = _main._fetch_update_manifest()
        version = manifest.get("version")
        installer_url = manifest.get("installer_url")
        sha256 = manifest.get("sha256")
        current_parts = _version_parts(APP_VERSION)
        remote_parts = _version_parts(version)
        if (
            current_parts is None
            or remote_parts is None
            or remote_parts <= current_parts
            or not _valid_installer_url(installer_url)
            or not _valid_sha256(sha256)
        ):
            return {"available": False}
        return {
            "available": True,
            "version": version,
            "changelog": manifest.get("changelog", ""),
        }
    except Exception:
        return {"available": False}


def _log_update_stage(stage: str, status: str, cause: str) -> None:
    record = {"stage": stage, "status": status, "cause": cause}
    logging.getLogger(_core_logging_setup.LOGGER_NAME).info(
        "update_stage=%s",
        json.dumps(record, sort_keys=True),
    )


def _update_http_failure_cause(stage: str, error: HTTPException) -> str:
    if stage == "check for update" and error.status_code == 403:
        return "request header is missing or invalid"
    if stage == "validate update info":
        if error.status_code == 409:
            return "no newer update is available"
        if error.detail == "The installer URL is invalid.":
            return "the installer link is invalid"
        if error.detail == "The installer checksum is invalid.":
            return "the installer checksum is missing or invalid"
    if stage == "verify checksum" and error.detail == "The installer checksum does not match.":
        return "the installer checksum did not match"
    return "the request was rejected"


def _raise_update_stage_failure(stage: str, error: Exception) -> None:
    cause = update_failure_cause(stage, error)
    _log_update_stage(stage, "failure", cause)
    next_step = {
        "check for update": "Check your internet connection and try again",
        "validate update info": "Check the version, installer link, and SHA-256 information",
        "find release on GitHub": "Check the GitHub release and try again",
        "download": "Check your connection and try again",
        "verify checksum": "Download the update again",
        "back up database": "Check database availability and permissions, then try again",
        "launch installer": "Check permissions or antivirus settings, then try again",
    }[stage]
    detail = f"Update failed at the {stage} step: {cause}. {next_step}."
    raise HTTPException(status_code=500, detail=detail) from error


@router.post("/api/updates/install")
def install_update(request: Request) -> dict:
    if request.headers.get("X-Clinthinker-Request") != "1":
        _log_update_stage(
            "check for update",
            "failure",
            "request header is missing or invalid",
        )
        raise HTTPException(status_code=403, detail="Missing required request header.")

    try:
        with suppress_check_exception_logging():
            manifest = _main._fetch_update_manifest()
    except HTTPException as error:
        _log_update_stage(
            "check for update",
            "failure",
            _update_http_failure_cause("check for update", error),
        )
        raise
    except Exception as error:
        _raise_update_stage_failure("check for update", error)
    else:
        _log_update_stage("check for update", "success", "update information fetched")

    try:
        remote_version = _version_parts(manifest.get("version"))
        current_version = _version_parts(APP_VERSION)
        if remote_version is None or current_version is None or remote_version <= current_version:
            raise HTTPException(status_code=409, detail="No newer update is available.")
        installer_url = manifest.get("installer_url")
        if not _valid_installer_url(installer_url):
            raise HTTPException(status_code=422, detail="The installer URL is invalid.")
        sha256 = manifest.get("sha256")
        if not _valid_sha256(sha256):
            raise HTTPException(status_code=422, detail="The installer checksum is invalid.")
    except HTTPException as error:
        _log_update_stage(
            "validate update info",
            "failure",
            _update_http_failure_cause("validate update info", error),
        )
        raise
    except Exception as error:
        _raise_update_stage_failure("validate update info", error)
    else:
        _log_update_stage(
            "validate update info",
            "success",
            "version, installer link, and checksum validated",
        )

    try:
        asset_url = _main._github_asset_api_url(installer_url)
    except HTTPException as error:
        _log_update_stage(
            "find release on GitHub",
            "failure",
            _update_http_failure_cause("find release on GitHub", error),
        )
        raise
    except Exception as error:
        _raise_update_stage_failure("find release on GitHub", error)
    else:
        _log_update_stage(
            "find release on GitHub",
            "success",
            "release installer was found",
        )

    try:
        update_directory = Path(tempfile.gettempdir()) / "clinthinker-updates"
        installer_path = update_directory / f"Clinthinker-Setup-{manifest['version']}.exe"
        with suppress_check_exception_logging():
            _main._download_update_asset(asset_url, installer_path)
    except HTTPException as error:
        _log_update_stage(
            "download",
            "failure",
            _update_http_failure_cause("download", error),
        )
        raise
    except Exception as error:
        _raise_update_stage_failure("download", error)
    else:
        _log_update_stage("download", "success", "installer download completed")

    try:
        digest = _main.hashlib.sha256()
        with installer_path.open("rb") as installer_file:
            while chunk := installer_file.read(1024 * 1024):
                digest.update(chunk)
        if digest.hexdigest().casefold() != sha256.casefold():
            installer_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail="The installer checksum does not match.")
    except HTTPException as error:
        _log_update_stage(
            "verify checksum",
            "failure",
            _update_http_failure_cause("verify checksum", error),
        )
        raise
    except Exception as error:
        _raise_update_stage_failure("verify checksum", error)
    else:
        _log_update_stage("verify checksum", "success", "installer checksum matched")

    try:
        if not database.DB_PATH.is_file():
            raise FileNotFoundError("The local database file was not found.")
        backup_time = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup_path = database.STORAGE / f"assistant-{backup_time}.sqlite3"
        with database.connect() as source:
            with closing(sqlite3.connect(backup_path)) as backup:
                source.backup(backup)
        with closing(sqlite3.connect(backup_path)) as verified_backup:
            integrity = verified_backup.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise sqlite3.DatabaseError("The database backup failed integrity_check.")
        try:
            backups = sorted(
                (
                    path
                    for path in database.STORAGE.glob("assistant-*.sqlite3")
                    if path.is_file()
                ),
                key=lambda path: path.stat().st_mtime_ns,
                reverse=True,
            )
            for old_backup in backups[5:]:
                old_backup.unlink()
        except Exception as error:
            logging.getLogger(_core_logging_setup.LOGGER_NAME).warning(
                "Unable to prune update backups: %s", error
            )
    except HTTPException as error:
        _log_update_stage(
            "back up database",
            "failure",
            _update_http_failure_cause("back up database", error),
        )
        raise
    except Exception as error:
        _raise_update_stage_failure("back up database", error)
    else:
        _log_update_stage(
            "back up database",
            "success",
            "database backup passed integrity check",
        )

    launch_options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        launch_options["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )

    try:
        subprocess.Popen(
            [str(installer_path), "/SILENT", "/NORESTART"],
            cwd=str(update_directory),
            **launch_options,
        )
    except HTTPException as error:
        _log_update_stage(
            "launch installer",
            "failure",
            _update_http_failure_cause("launch installer", error),
        )
        raise
    except Exception as error:
        _raise_update_stage_failure("launch installer", error)
    else:
        _log_update_stage("launch installer", "success", "installer process started")

    shutdown_callback = getattr(_main.app.state, "shutdown_callback", None)
    if shutdown_callback is not None:
        shutdown_timer = threading.Timer(1.5, shutdown_callback)
        shutdown_timer.daemon = True
        shutdown_timer.start()

    return {"started": True}
