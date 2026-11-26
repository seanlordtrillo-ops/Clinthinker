"""Classroom Quiz (lite): students answer a saved test on their phones.

How it works, in plain terms:
- The teacher starts a quiz from a saved test. The app opens a small, separate quiz
  server on the Wi-Fi or hotspot and shows a 4-digit room code.
- Students open the join address in their phone browser, type their name and the code,
  answer at their own pace and submit once. Answers are checked here, never on the phone.
- Every submission is written to the database the moment it arrives, so a crash or a
  closed laptop never loses submitted work (the teacher can recover it on next start).
- When the teacher ends the quiz, the quiz server stops and the submitted answers are
  saved as the test's class results, ready for Item Analysis.

Teacher controls while it runs: an optional time limit (phones count down and submit by
themselves at zero), locking the room so no one else can join, adding minutes, and
showing each student their corrections once everyone is done. Each student gets the
questions (and multiple-choice options) in their own order, and the teacher sees who
left the quiz page and how each question is going.

The quiz server can only show the page, join, get questions, submit, report status,
report leaving the page and show a student's own corrections after the teacher allows it.
It has no access to lessons, uploads, settings or other students' answers.
"""
from __future__ import annotations

import json
import logging
import random
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException

from . import assessments, item_analysis
from .database import connect

logger = logging.getLogger(__name__)

CODE_DIGITS = 4
MAX_STUDENTS = 200
MAX_NAME_LENGTH = 40
MAX_ANSWER_LENGTH = 200
DEFAULT_PORT = 8800
MAX_TIME_LIMIT_MINUTES = 180
# Phones submit by themselves at zero; this covers a slow network when they do.
LATE_SUBMIT_GRACE_SECONDS = 30
QUESTION_PREVIEW_LENGTH = 120
# (allowed requests, per seconds) for each client address and action.
RATE_LIMITS = {
    # Only wrong room codes count, so a whole class can join from one network quickly,
    # but guessing the code from one device takes hours.
    "wrong_code": (10, 60),
    "questions": (60, 60),
    "submit": (5, 60),
    "status": (120, 60),
    "away": (60, 60),
    "review": (30, 60),
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
    order: list[int] = field(default_factory=list)              # set numbers in this student's order
    choice_orders: dict[int, list[int]] = field(default_factory=dict)  # set number -> original option indexes
    answers: dict[int, str] | None = None
    submitted_at: str | None = None
    score: int | None = None
    graded: dict | None = None
    away: bool = False
    left_page: int = 0


@dataclass
class Session:
    test: dict
    code: str
    set_mode: str
    port: int
    started_at: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    state: str = "open"
    students: dict[str, Student] = field(default_factory=dict)
    join_count: int = 0
    shuffle: bool = True
    time_limit_minutes: int | None = None
    ends_at: float | None = None      # time.time() when the timer reaches zero
    locked: bool = False
    answers_released: bool = False


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


def _seconds_left(session: Session) -> int | None:
    if session.ends_at is None:
        return None
    return max(0, int(round(session.ends_at - time.time())))


def _submissions_closed(session: Session) -> str | None:
    """Why a submission must be refused right now, or None when it is allowed."""
    if session.answers_released:
        return "Your teacher has shown the answers, so submissions are closed."
    if session.ends_at is not None and time.time() > session.ends_at + LATE_SUBMIT_GRACE_SECONDS:
        return "Time is up. Answers can no longer be submitted."
    return None


def _orders_for(session: Session, token: str, set_label: str) -> tuple[list[int], dict[int, list[int]]]:
    """This student's question order (kept within each question type) and option orders."""
    entries = session.test["sets"][set_label]
    numbers = list(range(1, len(entries) + 1))
    if not session.shuffle:
        return numbers, {}
    rng = random.Random(f"{session.id}:{token}")
    order: list[int] = []
    for question_type in assessments.QUESTION_TYPE_ORDER:
        section = [
            number for number in numbers
            if session.test["items"][entries[number - 1]["item"]]["question_type"] == question_type
        ]
        rng.shuffle(section)
        order.extend(section)
    order.extend(number for number in numbers if number not in order)
    choice_orders = {}
    for number in numbers:
        entry = entries[number - 1]
        if session.test["items"][entry["item"]]["question_type"] == "Multiple Choice":
            indexes = list(range(len(entry["choices"])))
            rng.shuffle(indexes)
            choice_orders[number] = indexes
    return order, choice_orders


def _to_set_answer(student: Student, number: int, value: str) -> str:
    """A phone sends the letter it showed; turn it into the letter of the student's set."""
    indexes = student.choice_orders.get(number)
    letter = value.strip().upper().rstrip(".)")
    if indexes and len(letter) == 1 and letter in item_analysis.LETTERS[: len(indexes)]:
        return item_analysis.LETTERS[indexes[item_analysis.LETTERS.index(letter)]]
    return value


# ---------- saving submissions as they arrive ----------

def _store_submission(session: Session, student: Student) -> None:
    """Write one submission to the database right away. A failure here never blocks the
    student; the answers are still kept in memory and saved when the quiz ends."""
    try:
        with connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO classroom_submissions("
                "session_id, test_id, title, started_at, student_name, set_label, answers, score, submitted_at"
                ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session.id, session.test["id"], session.test["title"], session.started_at, student.name,
                 student.set_label, json.dumps(student.graded["answers"]), student.score, student.submitted_at),
            )
    except Exception:  # noqa: BLE001 - logged; never fail a student's submit because of it
        logger.exception("Could not store a classroom submission")


def _forget_submissions(session_id: str) -> None:
    with connect() as db:
        db.execute("DELETE FROM classroom_submissions WHERE session_id=?", (session_id,))


def unsaved_quizzes() -> list[dict]:
    """Quizzes that stopped without being ended (the app closed or crashed), with their
    stored submissions."""
    current = _session.id if _session is not None and _session.state == "open" else ""
    with connect() as db:
        rows = db.execute(
            "SELECT session_id, test_id, title, started_at, COUNT(*) AS submitted, MAX(submitted_at) AS last_submitted_at "
            "FROM classroom_submissions WHERE session_id<>? "
            "GROUP BY session_id, test_id, title, started_at ORDER BY started_at DESC",
            (current,),
        ).fetchall()
    return [dict(row) for row in rows]


def recover_quiz(session_id: str, *, save: bool) -> dict:
    """Save (or throw away) the stored submissions of a quiz that never ended."""
    with connect() as db:
        rows = db.execute(
            "SELECT test_id, title, student_name, set_label, answers, score FROM classroom_submissions "
            "WHERE session_id=? ORDER BY submitted_at",
            (session_id,),
        ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="That quiz has no unsaved answers.")
    if _session is not None and _session.state == "open" and _session.id == session_id:
        raise HTTPException(status_code=409, detail="That quiz is still running. End it instead.")
    test_id, title = rows[0]["test_id"], rows[0]["title"]
    result = {"test_id": test_id, "title": title, "submitted": len(rows), "saved": False}
    if save:
        try:
            assessments.load_test(test_id)
        except HTTPException as error:
            raise HTTPException(
                status_code=404,
                detail="The test for those answers was deleted, so they can't be saved. Discard them instead.",
            ) from error
        item_analysis.save_results(test_id, [
            {"name": row["student_name"], "set": row["set_label"],
             "answers": json.loads(row["answers"]), "score": row["score"]}
            for row in rows
        ])
        result["saved"] = True
    _forget_submissions(session_id)
    return result


# ---------- teacher side (called from the main app on this computer) ----------

def start_session(
    test_id: str,
    set_mode: str = "alternate",
    port: int = DEFAULT_PORT,
    *,
    time_limit_minutes: int | None = None,
    shuffle_questions: bool = True,
    server=None,
) -> dict:
    global _session
    test = assessments.load_test(test_id)
    if time_limit_minutes is not None and not 1 <= int(time_limit_minutes) <= MAX_TIME_LIMIT_MINUTES:
        raise HTTPException(status_code=422, detail=f"Choose a time limit from 1 to {MAX_TIME_LIMIT_MINUTES} minutes.")
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
            shuffle=bool(shuffle_questions),
            time_limit_minutes=int(time_limit_minutes) if time_limit_minutes else None,
            ends_at=time.time() + int(time_limit_minutes) * 60 if time_limit_minutes else None,
        )
    return session_status()


def control_session(
    *, locked: bool | None = None, add_minutes: int | None = None, release_answers: bool = False,
) -> dict:
    """Teacher controls while a quiz runs: lock joining, add time, show students their corrections."""
    with _lock:
        session = _session
        if session is None or session.state != "open":
            raise HTTPException(status_code=409, detail="No quiz is running.")
        if locked is not None:
            session.locked = bool(locked)
        if add_minutes:
            minutes = int(add_minutes)
            if not 1 <= minutes <= 60:
                raise HTTPException(status_code=422, detail="Add from 1 to 60 minutes.")
            # Adding time after it ran out restarts the countdown from now.
            start = max(session.ends_at or 0.0, time.time())
            session.ends_at = start + minutes * 60
            session.time_limit_minutes = (session.time_limit_minutes or 0) + minutes
        if release_answers:
            session.answers_released = True
            session.locked = True
    return session_status()


def _item_stats(session: Session) -> list[dict]:
    """How each question is going, numbered as in Set A. Counts submitted students only."""
    graded = [student.graded for student in session.students.values() if student.graded]
    by_item: dict[int, list[dict]] = defaultdict(list)
    for row in graded:
        for answer in row["answers"]:
            by_item[answer["item"]].append(answer)
    stats = []
    for number, entry in enumerate(session.test["sets"]["A"], start=1):
        item = session.test["items"][entry["item"]]
        answers = by_item.get(entry["item"], [])
        correct = sum(1 for answer in answers if answer["correct"])
        text = item["question_text"]
        stats.append({
            "number": number,
            "question": text if len(text) <= QUESTION_PREVIEW_LENGTH else text[: QUESTION_PREVIEW_LENGTH - 1] + "…",
            "topic": item.get("topic", ""),
            "type": item["question_type"],
            "submitted": len(answers),
            "answered": sum(1 for answer in answers if answer["chosen"] is not None),
            "correct": correct,
            "percent_correct": round(100 * correct / len(answers)) if answers else None,
        })
    return stats


def session_status() -> dict:
    from . import quiz_server

    from . import qr_code

    unsaved = _unsaved_or_empty()
    with _lock:
        if _session is None:
            status = {"running": False}
            if unsaved:
                status["unsaved_quizzes"] = unsaved
            return status
        students = sorted(_session.students.values(), key=lambda item: item.joined_at)
        submitted = [student for student in students if student.submitted_at]
        join_urls = [f"http://{address}:{_session.port}" for address in quiz_server.local_addresses()]
        seconds_left = _seconds_left(_session)
        status = {
            "running": _session.state == "open",
            "state": _session.state,
            "test_id": _session.test["id"],
            "title": _session.test["title"],
            "code": _session.code,
            "set_mode": _session.set_mode,
            "port": _session.port,
            "join_urls": join_urls,
            "join_qr_svg": qr_code.svg(join_urls[0]) if join_urls else None,
            "started_at": _session.started_at,
            "total_items": _session.test["total_items"],
            "shuffle_questions": _session.shuffle,
            "time_limit_minutes": _session.time_limit_minutes,
            "seconds_left": seconds_left,
            "time_up": seconds_left == 0,
            "locked": _session.locked,
            "answers_released": _session.answers_released,
            "joined": len(students),
            "submitted": len(submitted),
            "away_now": sum(1 for student in students if student.away and not student.submitted_at),
            "students": [
                {
                    "name": student.name,
                    "set": student.set_label,
                    "submitted": bool(student.submitted_at),
                    "score": student.score,
                    "away": student.away and not student.submitted_at,
                    "left_page": student.left_page,
                }
                for student in students
            ],
            "item_stats": _item_stats(_session),
        }
        if unsaved:
            status["unsaved_quizzes"] = unsaved
        return status


def _unsaved_or_empty() -> list[dict]:
    try:
        return unsaved_quizzes()
    except Exception:  # noqa: BLE001 - the status must still load
        logger.exception("Could not read unsaved classroom submissions")
        return []


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
        item_analysis.save_results(session.test["id"], [student.graded or _result_row(session, student) for student in submitted])
        result["saved"] = True
    elif save:
        result["message"] = "No one submitted, so the test's existing results were kept."
    _forget_submissions(session.id)
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
        if session.answers_released:
            raise HTTPException(status_code=403, detail="The quiz is over. Your teacher has shown the answers.")
        if session.locked:
            raise HTTPException(status_code=403, detail="Your teacher has closed joining. Ask your teacher to let you in.")
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
        token = secrets.token_urlsafe(18)
        order, choice_orders = _orders_for(session, token, set_label)
        student = Student(
            token=token,
            name=_unique_name(session, _clean_name(name)),
            set_label=set_label,
            address=address,
            joined_at=_now(),
            order=order,
            choice_orders=choice_orders,
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
        entries = session.test["sets"][student.set_label]
        questions = []
        for position, number in enumerate(student.order or range(1, len(entries) + 1), start=1):
            entry = entries[number - 1]
            item = session.test["items"][entry["item"]]
            indexes = student.choice_orders.get(number) or range(len(entry["choices"]))
            questions.append({
                "number": position,   # what the phone shows
                "key": number,        # what the phone sends back
                "type": item["question_type"],
                "text": item["question_text"],
                "choices": [entry["choices"][index] for index in indexes],
            })
        return {
            "title": session.test["title"],
            "name": student.name,
            "set": student.set_label,
            "submitted": bool(student.submitted_at),
            "score": student.score if student.submitted_at else None,
            "total": len(questions),
            "seconds_left": _seconds_left(session),
            "answers_released": session.answers_released,
            "closed_reason": _submissions_closed(session),
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
        closed = _submissions_closed(_session)
        if closed:
            raise HTTPException(status_code=410, detail=closed)
        total = _session.test["total_items"]
        cleaned: dict[int, str] = {}
        for key, value in answers.items():
            try:
                number = int(key)
            except (TypeError, ValueError):
                continue
            if 1 <= number <= total and isinstance(value, str):
                cleaned[number] = _to_set_answer(student, number, value.strip()[:MAX_ANSWER_LENGTH])
        student.answers = cleaned
        student.submitted_at = _now()
        student.away = False
        student.graded = _result_row(_session, student)
        student.score = student.graded["score"]
        _store_submission(_session, student)
        return {"submitted": True, "score": student.score, "total": total}


def student_status(token: str, address: str) -> dict:
    _limiter.check("status", address)
    with _lock:
        if _session is None or _session.state != "open":
            return {"state": "ended"}
        student = _session.students.get(str(token or ""))
        if student is None:
            return {"state": "unknown"}
        return {
            "state": "submitted" if student.submitted_at else "open",
            "seconds_left": _seconds_left(_session),
            "answers_released": _session.answers_released,
            "closed_reason": _submissions_closed(_session),
        }


def report_away(token: str, away: bool, address: str) -> dict:
    """The phone says the student left (or came back to) the quiz page."""
    _limiter.check("away", address)
    with _lock:
        student = _student(token)
        if student.submitted_at:
            return {"ok": True}
        away = bool(away)
        if away and not student.away:
            student.left_page += 1
        student.away = away
        return {"ok": True}


def review_for(token: str, address: str) -> dict:
    """A student's own corrections, only after the teacher shows the answers."""
    _limiter.check("review", address)
    with _lock:
        student = _student(token)
        session = _session
        if not session.answers_released:
            raise HTTPException(status_code=403, detail="Your teacher hasn't shown the answers yet.")
        if not student.submitted_at:
            raise HTTPException(status_code=403, detail="You didn't submit before the answers were shown.")
        entries = session.test["sets"][student.set_label]
        items = []
        for position, number in enumerate(student.order or range(1, len(entries) + 1), start=1):
            entry = entries[number - 1]
            item = session.test["items"][entry["item"]]
            chosen, correct = item_analysis._grade(item, entry["choices"], (student.answers or {}).get(number, ""))
            items.append({
                "number": position,
                "type": item["question_type"],
                "text": item["question_text"],
                "your_answer": chosen,
                "correct_answer": item["correct_answer"],
                "correct": correct,
            })
        return {
            "title": session.test["title"],
            "name": student.name,
            "score": student.score,
            "total": len(items),
            "items": items,
        }


def _reset_for_tests() -> None:
    global _session
    with _lock:
        _session = None
    _limiter.reset()
