from __future__ import annotations

from typing import Any


def build_error_record(
    file: str,
    function: str,
    expected_input_output: Any,
    actual_result: Any,
    probable_cause: str,
) -> dict[str, Any]:
    return {
        "file": str(file),
        "function": str(function),
        "expected input/output": expected_input_output,
        "actual result": actual_result,
        "probable cause": str(probable_cause),
    }


build_structured_error = build_error_record
