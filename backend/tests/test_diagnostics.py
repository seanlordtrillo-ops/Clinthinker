import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import database, diagnostics, main, ml


class DiagnosticsTests(unittest.TestCase):
    def test_run_all_passes_in_isolated_environment(self):
        report = diagnostics.run_all()
        self.assertTrue(report["passed"], report)
        self.assertEqual(
            [check["name"] for check in report["checks"]],
            ["database", "parsing", "ml", "questions", "updates", "uploads"],
        )

    def test_run_all_never_creates_the_configured_real_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            real_storage = Path(temporary) / "not-created"
            real_db_path = real_storage / "assistant.sqlite3"
            real_uploads = real_storage / "uploads"
            with patch.object(database, "STORAGE", real_storage), patch.object(
                database, "DB_PATH", real_db_path
            ), patch.object(database, "UPLOADS", real_uploads), patch.object(
                main, "UPLOADS", real_uploads
            ):
                ml._fit_models.cache_clear()
                report = diagnostics.run_all()
                cache_size = ml._fit_models.cache_info().currsize

            self.assertTrue(report["passed"], report)
            self.assertFalse(real_storage.exists())
            self.assertFalse(real_db_path.exists())
            self.assertEqual(cache_size, 0)

    def test_each_check_reports_structured_result(self):
        for check in (
            diagnostics.check_database,
            diagnostics.check_parsing,
            diagnostics.check_ml,
            diagnostics.check_questions,
            diagnostics.check_updates,
            diagnostics.check_uploads,
        ):
            result = check()
            self.assertIsInstance(result, dict)
            self.assertIn("name", result)
            self.assertIn("passed", result)
            self.assertIn("detail", result)

    def test_diagnostics_endpoint_is_read_only_and_returns_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            storage = Path(temporary)
            uploads = storage / "uploads"
            with patch.object(database, "STORAGE", storage), patch.object(
                database, "UPLOADS", uploads
            ), patch.object(database, "DB_PATH", storage / "assistant.sqlite3"), patch.object(
                main, "UPLOADS", uploads
            ):
                database.initialize()
                client = TestClient(main.app)
                response = client.get("/api/diagnostics")

        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), dict)
        self.assertIn("passed", response.json())
        self.assertIn("checks", response.json())

    def test_run_all_storage_override_is_thread_local(self):
        with tempfile.TemporaryDirectory() as temporary:
            real_storage = Path(temporary) / "real"
            real_uploads = real_storage / "uploads"
            real_db_path = real_storage / "assistant.sqlite3"
            with patch.object(database, "STORAGE", real_storage), patch.object(
                database, "UPLOADS", real_uploads
            ), patch.object(database, "DB_PATH", real_db_path):
                database.initialize()
                existing_paths = {
                    path.relative_to(real_storage) for path in real_storage.rglob("*")
                }
                check_started = threading.Event()
                continue_run = threading.Event()
                diagnostic_db_paths = []
                original_check_parsing = diagnostics.check_parsing

                def pause_diagnostics():
                    with database.connect() as db:
                        diagnostic_db_paths.append(
                            Path(db.execute("PRAGMA database_list").fetchone()["file"]).resolve()
                        )
                    check_started.set()
                    if not continue_run.wait(timeout=10):
                        raise TimeoutError("Diagnostics did not resume.")
                    return original_check_parsing()

                def write_real_row():
                    with database.connect() as db:
                        db_path = Path(
                            db.execute("PRAGMA database_list").fetchone()["file"]
                        ).resolve()
                        db.execute(
                            "CREATE TABLE IF NOT EXISTS concurrent_probe (value TEXT NOT NULL)"
                        )
                        db.execute(
                            "INSERT INTO concurrent_probe(value) VALUES(?)",
                            ("real-storage",),
                        )
                    return db_path

                with patch.object(
                    diagnostics, "check_parsing", side_effect=pause_diagnostics
                ):
                    with ThreadPoolExecutor(max_workers=2) as executor:
                        diagnostics_future = executor.submit(diagnostics.run_all)
                        try:
                            self.assertTrue(check_started.wait(timeout=10))
                            diagnostic_db_path = diagnostic_db_paths[0]
                            writer_future = executor.submit(write_real_row)
                            self.assertEqual(
                                writer_future.result(timeout=10), real_db_path.resolve()
                            )
                            with closing(
                                sqlite3.connect(diagnostic_db_path)
                            ) as diagnostic_db:
                                diagnostic_db.execute(
                                    "CREATE TABLE concurrent_probe (value TEXT NOT NULL)"
                                )
                                row = diagnostic_db.execute(
                                    "SELECT value FROM concurrent_probe "
                                    "WHERE value='real-storage'"
                                ).fetchone()
                            self.assertIsNone(row)
                        finally:
                            continue_run.set()
                        report = diagnostics_future.result(timeout=30)

                self.assertTrue(report["passed"], report)
                self.assertEqual(
                    {
                        path.relative_to(real_storage)
                        for path in real_storage.rglob("*")
                    },
                    existing_paths,
                )
                with database.connect() as db:
                    row = db.execute(
                        "SELECT value FROM concurrent_probe"
                    ).fetchone()
                self.assertEqual(row["value"], "real-storage")

    def test_run_all_resets_storage_override_when_check_raises(self):
        with tempfile.TemporaryDirectory() as temporary:
            real_storage = Path(temporary) / "real"
            real_uploads = real_storage / "uploads"
            real_db_path = real_storage / "assistant.sqlite3"
            with patch.object(database, "STORAGE", real_storage), patch.object(
                database, "UPLOADS", real_uploads
            ), patch.object(database, "DB_PATH", real_db_path):
                database.initialize()
                with patch.object(
                    diagnostics, "check_parsing", side_effect=RuntimeError("check failed")
                ):
                    with self.assertRaisesRegex(RuntimeError, "check failed"):
                        diagnostics.run_all()

                with database.connect() as db:
                    db_path = Path(
                        db.execute("PRAGMA database_list").fetchone()["file"]
                    ).resolve()
                self.assertEqual(db_path, real_db_path.resolve())
