import ast
import inspect
import json
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app import main, ml, questions
from app.core import checks as checks_module
from app.core.checks import checks
from app.services import updates


APPROVED_CHECKED_FUNCTIONS = (
    (main, "_analyze"),
    (main, "generate_practice_questions"),
    (main, "save_practice_questions"),
    (main, "upload_material"),
    (ml, "predict"),
    (ml, "evaluate_classifier"),
    (questions, "generate_questions"),
    (updates, "_fetch_update_manifest"),
    (updates, "_download_update_asset"),
)


class ChecksSyncTests(unittest.TestCase):
    def test_sync_return_value_is_unchanged(self):
        @checks(expected="value", probable_cause="test cause")
        def operation():
            return {"ok": True}

        self.assertEqual(operation(), {"ok": True})

    def test_sync_original_exception_is_reraised(self):
        original = ValueError("original message")

        @checks(expected="value", probable_cause="test cause")
        def operation():
            raise original

        with self.assertRaises(ValueError) as raised:
            operation()

        self.assertIs(raised.exception, original)

    def test_http_exception_is_logged_as_warning_and_reraised(self):
        logger = Mock()
        original = HTTPException(status_code=418, detail="unchanged body")

        @checks(expected="value", probable_cause="test cause")
        def operation():
            raise original

        with patch.object(checks_module, "logger", logger):
            with self.assertRaises(HTTPException) as raised:
                operation()

        self.assertIs(raised.exception, original)
        self.assertEqual(raised.exception.status_code, 418)
        self.assertEqual(raised.exception.detail, "unchanged body")
        logger.warning.assert_called_once()
        logger.error.assert_not_called()

    def test_unexpected_exception_is_logged_as_error(self):
        logger = Mock()
        original = RuntimeError("boom")

        @checks(expected="value", probable_cause="test cause")
        def operation():
            raise original

        with patch.object(checks_module, "logger", logger):
            with self.assertRaises(RuntimeError) as raised:
                operation()

        self.assertIs(raised.exception, original)
        logger.error.assert_called_once()
        logger.warning.assert_not_called()

        message = logger.error.call_args.args[1]
        record = json.loads(message)
        self.assertEqual(record["expected"], "value")
        self.assertIn("boom", record["actual"])
        self.assertEqual(record["probable cause"], "test cause")
        self.assertIn("function", record)
        self.assertIn("file", record)

    def test_logging_failure_does_not_replace_original_exception(self):
        logger = Mock()
        logger.error.side_effect = OSError("logger failed")
        original = ValueError("original failure")

        @checks(expected="value", probable_cause="test cause")
        def operation():
            raise original

        with patch.object(checks_module, "logger", logger):
            with self.assertRaises(ValueError) as raised:
                operation()

        self.assertIs(raised.exception, original)
        self.assertEqual(str(raised.exception), "original failure")

    def test_decorator_does_not_configure_or_change_logger_handlers(self):
        logger = checks_module.logger
        original_handlers = list(logger.handlers)
        original = ValueError("keep this error")

        @checks(expected="value", probable_cause="test cause")
        def operation():
            raise original

        with patch.object(logger, "error"), patch(
            "app.core.logging_setup.setup_logging"
        ) as setup_logging:
            with self.assertRaises(ValueError) as raised:
                operation()

        self.assertIs(raised.exception, original)
        self.assertEqual(logger.handlers, original_handlers)
        setup_logging.assert_not_called()

    def test_approved_functions_have_exactly_one_checks_wrapper(self):
        for module, function_name in APPROVED_CHECKED_FUNCTIONS:
            source = inspect.getsource(module)
            tree = ast.parse(source)
            function_node = next(
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == function_name
            )
            count = sum(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Name)
                and decorator.func.id == "checks"
                for decorator in function_node.decorator_list
            )
            with self.subTest(function=f"{module.__name__}.{function_name}"):
                self.assertEqual(count, 1)


class ChecksAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_return_value_is_unchanged(self):
        @checks(expected="value", probable_cause="test cause")
        async def operation():
            return ["unchanged"]

        self.assertEqual(await operation(), ["unchanged"])

    async def test_async_original_exception_is_reraised(self):
        original = LookupError("async original")

        @checks(expected="value", probable_cause="test cause")
        async def operation():
            raise original

        with self.assertRaises(LookupError) as raised:
            await operation()

        self.assertIs(raised.exception, original)
