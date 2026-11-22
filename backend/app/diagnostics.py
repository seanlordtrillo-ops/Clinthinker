from __future__ import annotations

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from . import database, ml, parsing, questions
from .services import updates


@contextmanager
def _isolated_storage():
    with tempfile.TemporaryDirectory() as temporary:
        storage = Path(temporary)
        with database.use_storage(storage) as uploads:
            database.initialize()
            yield uploads


def _result(name: str, passed: bool, detail: str = "") -> dict:
    return {
        "name": name,
        "passed": passed,
        "detail": detail,
    }


def check_database() -> dict:
    try:
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary)
            with database.use_storage(storage):
                database.initialize()
                settings = database.get_settings()
                if not isinstance(settings, dict):
                    return _result("database", False, "get_settings did not return a dictionary")
        return _result("database", True)
    except Exception as error:
        return _result("database", False, f"{type(error).__name__}: {error}")


def check_parsing() -> dict:
    try:
        text = parsing.extract_text("diagnostic.txt", b"Router forwards network packets.")
        if "router" not in text.lower():
            return _result("parsing", False, "Plain-text extraction did not contain expected text")
        return _result("parsing", True)
    except Exception as error:
        return _result("parsing", False, f"{type(error).__name__}: {error}")


def check_ml() -> dict:
    try:
        examples = [
            ("database relation primary key query", "Databases"),
            ("router packet network routing protocol", "Networking"),
        ]
        result = ml.predict("database primary key query", training_examples=examples)
        if not isinstance(result, list) or not result:
            return _result("ml", False, "predict did not return a ranked list")
        return _result("ml", True)
    except Exception as error:
        return _result("ml", False, f"{type(error).__name__}: {error}")


def check_questions() -> dict:
    try:
        with _isolated_storage():
            examples = [
                ("router routing packets network protocol", "Networking"),
                ("database relation primary key query", "Databases"),
            ]
            result = questions.generate_questions(
                requested_count=1,
                question_type="Multiple Choice",
                difficulty="Moderate",
                topic_filter="All Topics",
                per_topic=1,
                training_examples=examples,
                dataset_id="diagnostic",
                dataset_name="Diagnostic",
                sources=[
                    {
                        "id": "diagnostic",
                        "name": "diagnostic.txt",
                        "text": "Router forwards network packets using routing tables.",
                        "kind": "course",
                    }
                ],
            )
        if not isinstance(result, dict) or "questions" not in result:
            return _result("questions", False, "generate_questions did not return a question result")
        return _result("questions", True)
    except Exception as error:
        return _result("questions", False, f"{type(error).__name__}: {error}")


def check_updates() -> dict:
    try:
        url = updates.UPDATE_MANIFEST_URL
        if not isinstance(url, str) or not url.startswith("https://"):
            return _result("updates", False, "UPDATE_MANIFEST_URL is missing or invalid")
        if not updates._valid_sha256("a" * 64):
            return _result("updates", False, "_valid_sha256 rejected a valid checksum")
        return _result("updates", True)
    except Exception as error:
        return _result("updates", False, f"{type(error).__name__}: {error}")


def check_uploads() -> dict:
    try:
        with _isolated_storage() as uploads:
            destination = uploads / "diagnostic.txt"
            destination.write_bytes(b"Router forwards network packets.")
            with database.connect() as db:
                db.execute(
                    "INSERT INTO uploads(id, name, stored_path, bytes, text_chars) "
                    "VALUES(?, ?, ?, ?, ?)",
                    ("diagnostic", "diagnostic.txt", str(destination), 29, 29),
                )
                row = db.execute(
                    "SELECT id, name FROM uploads WHERE id=?",
                    ("diagnostic",),
                ).fetchone()
            if not row or row["id"] != "diagnostic":
                return _result("uploads", False, "Upload storage check did not persist metadata")
        return _result("uploads", True)
    except Exception as error:
        return _result("uploads", False, f"{type(error).__name__}: {error}")


def run_all() -> dict:
    checks: tuple[Callable[[], dict], ...] = (
        check_database,
        check_parsing,
        check_ml,
        check_questions,
        check_updates,
        check_uploads,
    )
    try:
        with _isolated_storage():
            results = [check() for check in checks]
        return {
            "passed": all(result["passed"] for result in results),
            "checks": results,
        }
    finally:
        ml._fit_models.cache_clear()


if __name__ == "__main__":
    report = run_all()
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)
