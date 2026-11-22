import json
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.core import checks as checks_module
from app.core.checks import checks


def _failing_helper():
    return 1 / 0  # LOCATION_MARKER


class ErrorLocationTests(unittest.TestCase):
    def _logged_record(self, function, logger_method="error"):
        logger = Mock()
        with patch.object(checks_module, "logger", logger):
            with self.assertRaises(Exception):
                function()
        method = getattr(logger, logger_method)
        method.assert_called_once()
        return json.loads(method.call_args.args[1]), method.call_args

    def test_record_contains_line_function_code_and_trace(self):
        @checks(expected="value", probable_cause="test cause")
        def operation():
            _failing_helper()

        record, _ = self._logged_record(operation)
        self.assertEqual(record["error_function"], "_failing_helper")
        self.assertIsInstance(record["error_line"], int)
        self.assertIn("LOCATION_MARKER", record["error_code"])
        self.assertTrue(record["error_file"].endswith("test_checks_locations.py"))
        self.assertTrue(any("_failing_helper" in step for step in record["trace"]))
        self.assertLessEqual(len(record["trace"]), 5)

    def test_existing_record_keys_are_unchanged(self):
        @checks(expected="value", probable_cause="test cause")
        def operation():
            raise RuntimeError("boom")

        record, _ = self._logged_record(operation)
        self.assertEqual(record["expected"], "value")
        self.assertIn("boom", record["actual"])
        self.assertEqual(record["probable cause"], "test cause")
        self.assertIn("function", record)
        self.assertIn("file", record)

    def test_unexpected_error_also_logs_full_traceback(self):
        @checks()
        def operation():
            raise RuntimeError("boom")

        _, call = self._logged_record(operation)
        self.assertIsInstance(call.kwargs.get("exc_info"), RuntimeError)

    def test_http_exception_stays_a_short_warning(self):
        @checks()
        def operation():
            raise HTTPException(status_code=422, detail="bad input")

        record, call = self._logged_record(operation, "warning")
        self.assertIn("error_line", record)
        self.assertNotIn("exc_info", call.kwargs)

    def test_original_exception_is_still_reraised_unchanged(self):
        original = ValueError("keep me")

        @checks()
        def operation():
            raise original

        with patch.object(checks_module, "logger", Mock()):
            with self.assertRaises(ValueError) as raised:
                operation()
        self.assertIs(raised.exception, original)

    def test_location_failure_never_breaks_logging(self):
        @checks()
        def operation():
            raise RuntimeError("boom")

        logger = Mock()
        with patch.object(checks_module, "logger", logger), patch.object(
            checks_module, "_error_location", side_effect=RuntimeError("bad")
        ):
            with self.assertRaises(RuntimeError):
                operation()
        logger.error.assert_called_once()
        self.assertNotIn("error_line", json.loads(logger.error.call_args.args[1]))

    def test_error_without_traceback_is_handled(self):
        self.assertEqual(checks_module._error_location(ValueError("no tb")), {})


class AsyncErrorLocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_function_records_location(self):
        @checks(expected="value", probable_cause="test cause")
        async def operation():
            _failing_helper()

        logger = Mock()
        with patch.object(checks_module, "logger", logger):
            with self.assertRaises(ZeroDivisionError):
                await operation()
        record = json.loads(logger.error.call_args.args[1])
        self.assertEqual(record["error_function"], "_failing_helper")


if __name__ == "__main__":
    unittest.main()
