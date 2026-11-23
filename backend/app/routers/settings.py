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

from app import main as _main

router = APIRouter()


@router.get("/api/settings")
def read_settings() -> dict:
    return get_settings()


@router.put("/api/settings")
def update_settings(request: SettingsUpdate) -> dict:
    return save_settings(request.model_dump(exclude_none=True))
