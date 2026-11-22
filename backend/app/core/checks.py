from __future__ import annotations

import functools
import inspect
import json
import logging
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterator, ParamSpec, TypeVar

from fastapi import HTTPException

from .logging_setup import LOGGER_NAME


P = ParamSpec("P")
R = TypeVar("R")
logger = logging.getLogger(LOGGER_NAME)
# Folder that holds the app's own code (backend/app). Used to prefer the app's
# frames over library frames when reporting where an error happened.
_APP_ROOT = Path(__file__).resolve().parents[1]
_TRACE_DEPTH = 5
_CODE_LINE_LIMIT = 200
_exception_logging_suppressed: ContextVar[bool] = ContextVar(
    "exception_logging_suppressed",
    default=False,
)


@contextmanager
def suppress_check_exception_logging() -> Iterator[None]:
    token = _exception_logging_suppressed.set(True)
    try:
        yield
    finally:
        _exception_logging_suppressed.reset(token)


def checks(
    expected: Any = "successful execution",
    probable_cause: str = "Unexpected exception",
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(function: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(function)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return function(*args, **kwargs)
            except Exception as error:
                if not _exception_logging_suppressed.get():
                    _log_exception(function, expected, probable_cause, error)
                raise

        @functools.wraps(function)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return await function(*args, **kwargs)
            except Exception as error:
                if not _exception_logging_suppressed.get():
                    _log_exception(function, expected, probable_cause, error)
                raise

        if inspect.iscoroutinefunction(function):
            return async_wrapper
        return sync_wrapper

    return decorator


def _error_location(error: BaseException) -> dict[str, Any]:
    """Where the error was raised: file, line, function, code and a short trace.

    Prefers frames from this app's own code; falls back to every frame when the
    error happened entirely inside a library. Returns {} if no traceback exists.
    """
    all_frames = traceback.extract_tb(error.__traceback__)
    # Skip this decorator's own wrapper frames so the report points at real code.
    frames = [frame for frame in all_frames if frame.filename != __file__] or list(all_frames)
    if not frames:
        return {}

    def is_app_frame(frame: traceback.FrameSummary) -> bool:
        try:
            Path(frame.filename).resolve().relative_to(_APP_ROOT)
            return True
        except (ValueError, OSError):
            return False

    app_frames = [frame for frame in frames if is_app_frame(frame)]
    origin = (app_frames or frames)[-1]
    code_line = (origin.line or "").strip()
    return {
        "error_file": str(origin.filename),
        "error_line": origin.lineno,
        "error_function": origin.name,
        "error_code": code_line[:_CODE_LINE_LIMIT],
        "trace": [
            f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}"
            for frame in frames[-_TRACE_DEPTH:]
        ],
    }


def _log_exception(
    function: Callable,
    expected: Any,
    probable_cause: str,
    error: Exception,
) -> None:
    try:
        record = {
            "file": str(function.__code__.co_filename),
            "function": function.__qualname__,
            "expected": expected,
            "actual": f"{type(error).__name__}: {error}",
            "probable cause": probable_cause,
        }
        try:
            record.update(_error_location(error))
        except Exception:
            # Location details are a bonus; never let them break logging.
            pass
        message = json.dumps(record, sort_keys=True, default=str)
        if isinstance(error, HTTPException):
            # Expected, user-facing errors: keep the log short.
            logger.warning("structured_error=%s", message)
        else:
            # Unexpected errors also get the full Python traceback in the log.
            logger.error("structured_error=%s", message, exc_info=error)
    except Exception:
        pass
