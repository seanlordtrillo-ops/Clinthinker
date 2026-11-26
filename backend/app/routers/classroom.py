"""Teacher routes for the Classroom Quiz. These stay on the main app (this computer only);
phones talk to the separate quiz server in app/quiz_server.py."""
from __future__ import annotations

from fastapi import APIRouter

from .. import classroom
from ..schemas import (
    ClassroomControlRequest,
    EndClassroomRequest,
    RecoverClassroomRequest,
    StartClassroomRequest,
)

router = APIRouter()


@router.get("/api/classroom")
def read_classroom() -> dict:
    return classroom.session_status()


@router.post("/api/classroom/start")
def start_classroom(request: StartClassroomRequest) -> dict:
    return classroom.start_session(
        request.test_id,
        request.set_mode,
        request.port,
        time_limit_minutes=request.time_limit_minutes,
        shuffle_questions=request.shuffle_questions,
    )


@router.post("/api/classroom/control")
def control_classroom(request: ClassroomControlRequest) -> dict:
    return classroom.control_session(
        locked=request.locked,
        add_minutes=request.add_minutes,
        release_answers=request.release_answers,
    )


@router.post("/api/classroom/end")
def end_classroom(request: EndClassroomRequest) -> dict:
    return classroom.end_session(save=request.save)


@router.post("/api/classroom/recover")
def recover_classroom(request: RecoverClassroomRequest) -> dict:
    return classroom.recover_quiz(request.session_id, save=request.save)
