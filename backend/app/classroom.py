"""Classroom Quiz (lite): students answer a saved test on their phones.

How it works, in plain terms:
- The teacher starts a quiz from a saved test. The app opens a small, separate quiz
  server on the Wi-Fi or hotspot and shows a 4-digit room code.
- Students open the join address in their phone browser, type their name and the code,
  answer at their own pace and submit once. Answers are checked here, never on the phone.
- When the teacher ends the quiz, the quiz server stops and the submitted answers are
  saved as the test's class results, ready for Item Analysis.

The quiz server can only do four things (show the page, join, get questions, submit).
It has no access to lessons, uploads, settings or answer keys.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException

from . import assessments, item_analysis

CODE_DIGITS = 4
MAX_STUDENTS = 200
MAX_NAME_LENGTH = 40
MAX_ANSWER_LENGTH = 200
DEFAULT_PORT = 8800
# (allowed requests, per seconds) for each client address and action.
RATE_LIMITS = {
    # Only wrong room codes count, so a whole class can join from one network quickly,
    # but guessing the code from one device takes hours.
    "wrong_code": (10, 60),
    "questions": (60, 60),
    "submit": (5, 60),
    "status": (120, 60),
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Student:
    token: str
    name: str
    set_label: str
    address: str
    joined_at: str
    answers: dict[int, str] | None = None
    submitted_at: str | None = None
    score: int | None = None


@dataclass
class Session:
    test: dict
    code: str
    set_mode: str
    port: int
    started_at: str
    state: str = "open"
    students: dict[str, Student] = field(default_factory=dict)
    join_count: int = 0


class RateLimiter:
    def __init__(self, limits: dict[str, tuple[int, int]]):
        self.limits = limits
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, action: str, address: str, *, record: bool = True) -> None:
        """Refuse when the address used up its tries; otherwise count this one."""
        allowed, window = self.limits[action]
        now = time.monotonic()
        with self.lock:
            hits = self.hits[(action, address)]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= allowed:
                raise HTTPException(status_code=429, detail="Too many tries. Wait a minute and try again.")
            if record:
                hits.append(now)

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()


_lock = threading.RLock()
_session: Session | None = None
_limiter = RateLimiter(RATE_LIMITS)


def _clean_name(name: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f<>]", "", str(name or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:MAX_NAME_LENGTH].strip()
    if not cleaned:
        raise HTTPException(status_code=422, detail="Type your name.")
    return cleaned


def _unique_name(session: Session, name: str) -> str:
    taken = {student.name.casefold() for student in session.students.values()}
    if name.casefold() not in taken:
        return name
    number = 2
    while f"{name} ({number})".casefold() in taken:
        number += 1
    return f"{name} ({number})"


def _require_session() -> Session:
    if _session is None or _session.state != "open":
        raise HTTPException(status_code=410, detail="This quiz has ended.")
    return _session


def _student(token: str) -> Student:
    session = _require_session()
    student = session.students.get(str(token or ""))
    if student is None:
        raise HTTPException(status_code=401, detail="Join the quiz again with the room code.")
    return student


# ---------- teacher side (called from the main app on this computer) ----------

def start_session(test_id: str, set_mode: str = "alternate", port: int = DEFAULT_PORT, *, server=None) -> dict:
    global _session
    test = assessments.load_test(test_id)
    if set_mode not in {"A", "B", "alternate"}:
        raise HTTPException(status_code=422, detail="Choose Set A, Set B or alternate sets.")
    if set_mode in {"B", "alternate"} and "B" not in test["sets"]:
        if set_mode == "B":
            raise HTTPException(status_code=422, detail="This test has no Set B.")
        set_mode = "A"
    with _lock:
        if _session is not None and _session.state == "open":
            raise HTTPException(status_code=409, detail="A quiz is already running. End it first.")
        from . import quiz_server

        running_port = (server or quiz_server.SERVER).start(port)
        _limiter.reset()
        _session = Session(
            test=test,
            code=f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}",
            set_mode=set_mode,
            port=running_port,
            started_at=_now(),
        )
    return session_status()


def session_status() -> dict:
    from . import quiz_server

    with _lock:
        if _session is None:
            return {"running": False}
        students = sorted(_session.students.values(), key=lambda item: item.joined_at)
        submitted = [student for student in students if student.submitted_at]
        return {
            "running": _session.state == "open",
            "state": _session.state,
            "test_id": _session.test["id"],
            "title": _session.test["title"],
            "code": _session.code,
            "set_mode": _session.set_mode,
            "port": _session.port,
            "join_urls": [f"http://{address}:{_session.port}" for address in quiz_server.local_addresses()],
            "started_at": _session.started_at,
            "total_items": _session.test["total_items"],
            "joined": len(students),
            "submitted": len(submitted),
            "students": [
                {
                    "name": student.name,
                    "set": student.set_label,
                    "submitted": bool(student.submitted_at),
                    "score": student.score,
                }
                for student in students
            ],
        }


def end_session(*, save: bool = True, server=None) -> dict:
    """Stop the quiz server and save submitted answers as the test's class results."""
    global _session
    from . import quiz_server

    with _lock:
        if _session is None or _session.state != "open":
            raise HTTPException(status_code=409, detail="No quiz is running.")
        _session.state = "ended"
        session = _session
    (server or quiz_server.SERVER).stop()
    submitted = [student for student in session.students.values() if student.submitted_at]
    result = {
        "test_id": session.test["id"],
        "joined": len(session.students),
        "submitted": len(submitted),
        "not_submitted": [student.name for student in session.students.values() if not student.submitted_at],
        "saved": False,
    }
    if save and submitted:
        item_analysis.save_results(session.test["id"], [_result_row(session, student) for student in submitted])
        result["saved"] = True
    elif save:
        result["message"] = "No one submitted, so the test's existing results were kept."
    return result


def _result_row(session: Session, student: Student) -> dict:
    answers = []
    for number, entry in enumerate(session.test["sets"][student.set_label], start=1):
        item = session.test["items"][entry["item"]]
        chosen, correct = item_analysis._grade(item, entry["choices"], (student.answers or {}).get(number, ""))
        answers.append({"item": entry["item"], "chosen": chosen, "correct": correct})
    answers.sort(key=lambda answer: answer["item"])
    return {
        "name": student.name,
        "set": student.set_label,
        "answers": answers,
        "score": sum(answer["correct"] for answer in answers),
    }


# ---------- student side (called by the quiz server for phones) ----------

def join(code: str, name: str, address: str) -> dict:
    _limiter.check("wrong_code", address, record=False)
    with _lock:
        session = _require_session()
        if not secrets.compare_digest(str(code or "").strip(), session.code):
            _limiter.check("wrong_code", address)
            raise HTTPException(status_code=403, detail="That room code is not correct.")
        if len(session.students) >= MAX_STUDENTS:
            raise HTTPException(status_code=409, detail="This quiz is full.")
        if session.set_mode == "alternate":
            set_label = "AB"[session.join_count % 2]
        else:
            set_label = session.set_mode
        session.join_count += 1
        student = Student(
            token=secrets.token_urlsafe(18),
            name=_unique_name(session, _clean_name(name)),
            set_label=set_label,
            address=address,
            joined_at=_now(),
        )
        session.students[student.token] = student
        return {
            "token": student.token,
            "name": student.name,
            "set": set_label,
            "title": session.test["title"],
            "total_items": session.test["total_items"],
        }


def questions_for(token: str, address: str) -> dict:
    _limiter.check("questions", address)
    with _lock:
        student = _student(token)
        session = _session
        questions = []
        for number, entry in enumerate(session.test["sets"][student.set_label], start=1):
            item = session.test["items"][entry["item"]]
            questions.append({
                "number": number,
                "type": item["question_type"],
                "text": item["question_text"],
                "choices": list(entry["choices"]),
            })
        return {
            "title": session.test["title"],
            "name": student.name,
            "set": student.set_label,
            "submitted": bool(student.submitted_at),
            "score": student.score if student.submitted_at else None,
            "total": len(questions),
            "questions": questions,
        }


def submit(token: str, answers: dict, address: str) -> dict:
    _limiter.check("submit", address)
    if not isinstance(answers, dict):
        raise HTTPException(status_code=422, detail="Send your answers again.")
    with _lock:
        student = _student(token)
        if student.submitted_at:
            raise HTTPException(status_code=409, detail="You already submitted.")
        total = _session.test["total_items"]
        cleaned: dict[int, str] = {}
        for key, value in answers.items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= total and isinstance(value, str):
                cleaned[number] = value.strip()[:MAX_ANSWER_LENGTH]
        student.answers = cleaned
        student.submitted_at = _now()
        student.score = _result_row(_session, student)["score"]
        return {"submitted": True, "score": student.score, "total": total}


def student_status(token: str, address: str) -> dict:
    _limiter.check("status", address)
    with _lock:
        if _session is None or _session.state != "open":
            return {"state": "ended"}
        student = _session.students.get(str(token or ""))
        if student is None:
            return {"state": "unknown"}
        return {"state": "submitted" if student.submitted_at else "open"}


def _reset_for_tests() -> None:
    global _session
    with _lock:
        _session = None
    _limiter.reset()
