"""Teacher routes for the Classroom Quiz. These stay on the main app (this computer only);
phones talk to the separate quiz server in app/quiz_server.py."""
from __future__ import annotations

from fastapi import APIRouter

from .. import classroom
from ..schemas import EndClassroomRequest, StartClassroomRequest

router = APIRouter()


@router.get("/api/classroom")
def read_classroom() -> dict:
    return classroom.session_status()


@router.post("/api/classroom/start")
def start_classroom(request: StartClassroomRequest) -> dict:
    return classroom.start_session(request.test_id, request.set_mode, request.port)


@router.post("/api/classroom/end")
def end_classroom(request: EndClassroomRequest) -> dict:
    return classroom.end_session(save=request.save)
