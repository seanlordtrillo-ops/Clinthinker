"""Routes for the Test Builder (TOS, Set A/B, Word exports) and Item Analysis."""
from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .. import assessments, item_analysis
from ..parsing import read_limited
from ..schemas import BuildTestRequest, RenameTestRequest

router = APIRouter()
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_MAX_RESULTS_BYTES = 2 * 1024 * 1024


def _file_name(title: str, suffix: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")[:60] or "test"
    return f"{safe}-{suffix}"


@router.post("/api/tests")
def build_test(request: BuildTestRequest) -> dict:
    return assessments.build_test(
        title=request.title,
        training_dataset_id=request.training_dataset_id,
        lesson_upload_ids=request.lesson_upload_ids,
        total_items=request.total_items,
        question_types=request.question_types,
        items_per_topic=request.items_per_topic,
        include_set_b=request.include_set_b,
    )


@router.get("/api/tests")
def list_tests() -> dict:
    return assessments.list_tests()


@router.get("/api/tests/{test_id}")
def read_test(test_id: str) -> dict:
    return assessments.with_answer_keys(assessments.load_test(test_id))


@router.put("/api/tests/{test_id}")
def rename_test(test_id: str, request: RenameTestRequest) -> dict:
    return assessments.rename_test(test_id, request.title)


@router.delete("/api/tests/{test_id}")
def delete_test(test_id: str) -> dict:
    return assessments.delete_test(test_id)


@router.get("/api/tests/{test_id}/export")
def export_test(
    test_id: str,
    document: Literal["test", "key", "tos"] = "test",
    set_label: str = "A",
) -> Response:
    test = assessments.load_test(test_id)
    if document == "test":
        if set_label not in test["sets"]:
            raise HTTPException(status_code=404, detail=f"This test has no Set {set_label}.")
        content = assessments.export_test_paper(test, set_label)
        name = _file_name(test["title"], f"Set-{set_label}.docx")
    elif document == "key":
        content = assessments.export_answer_key(test)
        name = _file_name(test["title"], "Answer-Key.docx")
    else:
        content = assessments.export_specification(test)
        name = _file_name(test["title"], "TOS.docx")
    return Response(
        content=content,
        media_type=_DOCX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/api/tests/{test_id}/results-template")
def results_template(test_id: str) -> Response:
    test = assessments.load_test(test_id)
    return Response(
        content=item_analysis.results_template(test),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{_file_name(test["title"], "results.csv")}"'},
    )


@router.post("/api/tests/{test_id}/results")
async def import_results(test_id: str, file: UploadFile = File(...)) -> dict:
    name = (file.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(status_code=415, detail="Choose a CSV file of the class's answers.")
    content = await read_limited(file, _MAX_RESULTS_BYTES)
    return await run_in_threadpool(item_analysis.import_results, test_id, content)


@router.get("/api/tests/{test_id}/analysis")
def read_analysis(test_id: str) -> dict:
    return item_analysis.analyze(test_id)
