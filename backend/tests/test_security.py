import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app import database, main
from app.core import checks as checks_module
from app.core.security import LocalRequestGuard, host_name, is_local_origin, rejection
from app.routers import questions as questions_router
from app.schemas import GenerateQuestionsRequest


def run_guard(method="GET", path="/api/health", headers=None):
    """Send one fake HTTP request through the guard and return (status, reached_app)."""
    reached = []
    sent = []

    async def app(scope, receive, send):
        reached.append(scope["path"])

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(key.encode(), value.encode()) for key, value in (headers or {}).items()],
    }
    asyncio.run(LocalRequestGuard(app)(scope, receive, send))
    status = sent[0]["status"] if sent else None
    return status, bool(reached), sent


class RequestGuardTests(unittest.TestCase):
    def test_host_names_are_read_without_ports(self):
        self.assertEqual(host_name("localhost:5173"), "localhost")
        self.assertEqual(host_name("127.0.0.1"), "127.0.0.1")
        self.assertEqual(host_name("[::1]:8000"), "::1")
        self.assertEqual(host_name("Evil.Example:80"), "evil.example")

    def test_local_origins(self):
        self.assertTrue(is_local_origin("http://localhost:5173"))
        self.assertTrue(is_local_origin("http://127.0.0.1:61234"))
        self.assertFalse(is_local_origin("https://evil.example"))
        self.assertFalse(is_local_origin("null"))

    def test_the_apps_own_requests_pass(self):
        for headers in (
            {"host": "127.0.0.1:61234", "origin": "http://127.0.0.1:61234", "sec-fetch-site": "same-origin"},
            {"host": "localhost:5173", "origin": "http://localhost:5173"},
            {"host": "testserver"},
            {},
        ):
            with self.subTest(headers=headers):
                self.assertIsNone(rejection("POST", "/api/upload", headers))
                status, reached, _ = run_guard("POST", "/api/upload", headers)
                self.assertTrue(reached)
                self.assertIsNone(status)

    def test_unknown_host_names_are_blocked(self):
        status, reached, sent = run_guard("GET", "/api/uploads", {"host": "attacker.example"})
        self.assertEqual(status, 400)
        self.assertFalse(reached)
        self.assertIn("unknown address", json.loads(sent[1]["body"])["detail"])

    def test_other_websites_cannot_change_data(self):
        cases = [
            {"host": "127.0.0.1:8000", "origin": "https://attacker.example"},
            {"host": "127.0.0.1:8000", "origin": "null"},
            {"host": "127.0.0.1:8000", "sec-fetch-site": "cross-site"},
        ]
        for headers in cases:
            for method in ("POST", "PUT", "DELETE"):
                with self.subTest(headers=headers, method=method):
                    status, reached, _ = run_guard(method, "/api/upload", headers)
                    self.assertEqual(status, 403)
                    self.assertFalse(reached)

    def test_reading_is_left_to_cors(self):
        status, reached, _ = run_guard("GET", "/api/uploads", {"host": "127.0.0.1", "origin": "https://attacker.example"})
        self.assertIsNone(status)
        self.assertTrue(reached)

    def test_non_http_traffic_passes_through(self):
        reached = []

        async def app(scope, receive, send):
            reached.append(scope["type"])

        asyncio.run(LocalRequestGuard(app)({"type": "lifespan"}, None, None))
        self.assertEqual(reached, ["lifespan"])


class RouteLoggingAndExamOptionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        storage = Path(temporary.name)
        uploads = storage / "uploads"
        for item in (
            patch.object(database, "STORAGE", storage),
            patch.object(database, "UPLOADS", uploads),
            patch.object(database, "DB_PATH", storage / "assistant.sqlite3"),
            patch.object(main, "UPLOADS", uploads),
        ):
            item.start()
            self.addCleanup(item.stop)
        database.initialize()
        uploads.mkdir(parents=True, exist_ok=True)
        lesson = uploads / "lesson-1.txt"
        lesson.write_text(
            "Usability is the extent to which users can reach goals effectively.\n"
            "A prototype is an early model of a design used to test ideas.\n",
            encoding="utf-8",
        )
        with database.connect() as db:
            db.execute(
                "INSERT INTO uploads(id, name, stored_path, bytes, text_chars) VALUES(?, ?, ?, ?, ?)",
                ("lesson-1", "Lesson.txt", str(lesson.resolve()), 10, 10),
            )
        main._question_batches.clear()
        self.addCleanup(main._question_batches.clear)

    def request(self, **changes):
        fields = {
            "training_dataset_id": "builtin",
            "upload_ids": ["lesson-1"],
            "lesson_upload_ids": ["lesson-1"],
            "lesson_only": True,
            "question_type": "Multiple Choice",
            "difficulty": "Moderate",
            "number_of_questions": 2,
            **changes,
        }
        return GenerateQuestionsRequest(**fields)

    def test_route_errors_are_logged_once(self):
        logger = Mock()
        bad = self.request(upload_ids=["lesson-1", "lesson-1"])
        for call in (questions_router.generate_practice_questions, main.generate_practice_questions):
            logger.reset_mock()
            with self.subTest(call=call.__module__), patch.object(checks_module, "logger", logger):
                with self.assertRaises(HTTPException):
                    call(bad)
                logger.warning.assert_called_once()

    def test_registered_routes_are_the_logged_entry_points(self):
        endpoints = {route.path: route.endpoint for route in main.app.router.routes if hasattr(route, "endpoint")}
        self.assertIs(endpoints["/api/questions/generate"], questions_router.generate_practice_questions)
        self.assertTrue(hasattr(questions_router, "_generate_practice_questions"))
        self.assertTrue(hasattr(questions_router._generate_practice_questions, "__wrapped__"))

    def test_past_exams_only_affect_classification_when_the_option_is_on(self):
        augment = Mock(side_effect=lambda examples, *args, **kwargs: (examples, 0))
        with patch.object(main, "augment_training_examples_with_exam_passages", augment):
            main.generate_practice_questions(self.request(use_exam_style=False))
            augment.assert_not_called()
            main.generate_practice_questions(self.request(use_exam_style=True))
            augment.assert_called_once()


if __name__ == "__main__":
    unittest.main()
