import unittest

from app.core.errors import build_error_record, build_structured_error


class StructuredErrorTests(unittest.TestCase):
    def test_builds_structured_error_record(self):
        record = build_error_record(
            file="/app/module.py",
            function="process",
            expected_input_output={"count": 2},
            actual_result={"count": 1},
            probable_cause="One item was omitted",
        )

        self.assertEqual(
            record,
            {
                "file": "/app/module.py",
                "function": "process",
                "expected input/output": {"count": 2},
                "actual result": {"count": 1},
                "probable cause": "One item was omitted",
            },
        )

    def test_alias_builds_the_same_record(self):
        record = build_structured_error(
            "module.py",
            "run",
            "valid output",
            "exception",
            "invalid input",
        )

        self.assertEqual(record["file"], "module.py")
        self.assertEqual(record["function"], "run")
        self.assertEqual(record["expected input/output"], "valid output")
        self.assertEqual(record["actual result"], "exception")
        self.assertEqual(record["probable cause"], "invalid input")
