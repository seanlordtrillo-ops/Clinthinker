"""Item analysis for a built test: import the class's answers from a CSV and compute,
for every item, the difficulty index, the discrimination index and a decision
(retain, revise or discard), plus distractor analysis and KR-20 reliability.

Formulas (the standard classroom item analysis):
- Difficulty index p = students who got the item right / students who took the test.
- Discrimination index D = (right in the upper 27%) - (right in the lower 27%),
  divided by the number of students in one group.
- KR-20 = k/(k-1) x (1 - sum(p x q) / variance of total scores), with q = 1 - p.
"""
from __future__ import annotations

import csv
import io
import json
import re
import statistics
import uuid
from collections import Counter
from typing import Mapping, Sequence

from fastapi import HTTPException

from .assessments import LETTERS, load_test
from .core.checks import checks
from .database import connect
from .progress import is_correct_answer, normalize_answer

MAX_STUDENTS = 1000
GROUP_SHARE = 0.27
FEW_STUDENTS = 20
_ITEM_HEADER = re.compile(r"^(?:q|item|no\.?|#|number)?\s*(\d{1,3})$", re.IGNORECASE)


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")


def results_template(test: Mapping) -> str:
    """A CSV the teacher fills in: one row per student, one column per item."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["student", "set", *range(1, test["total_items"] + 1)])
    for label in sorted(test["sets"]):
        writer.writerow([f"Sample student (Set {label})", label, *[""] * test["total_items"]])
    return output.getvalue()


def _grade(item: Mapping, choices: Sequence[str], raw: str) -> tuple[str | None, bool]:
    """Turn what the student wrote into (chosen answer, correct?)."""
    raw = str(raw or "").strip()
    if not raw:
        return None, False
    answer = item["correct_answer"]
    if item["question_type"] == "Multiple Choice":
        letter = raw.upper().rstrip(".)")
        if len(letter) == 1 and letter in LETTERS[: len(choices)]:
            chosen = choices[LETTERS.index(letter)]
        else:
            chosen = next((choice for choice in choices if normalize_answer(choice) == normalize_answer(raw)), raw)
        return chosen, chosen == answer
    if item["question_type"] == "True or False":
        value = normalize_answer(raw)
        chosen = "True" if value in {"t", "true"} else "False" if value in {"f", "false"} else raw
        return chosen, chosen == answer
    return raw, is_correct_answer("Identification", raw, answer)


def parse_results(test: Mapping, content: bytes) -> tuple[list[dict], list[str]]:
    text = _decode(content)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect) if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise HTTPException(status_code=422, detail="The CSV needs a header row and at least one student.")
    header = [cell.strip() for cell in rows[0]]
    item_columns: dict[int, int] = {}
    name_column = set_column = None
    for column, cell in enumerate(header):
        match = _ITEM_HEADER.match(cell)
        if match:
            item_columns[int(match.group(1))] = column
        elif cell.casefold() in {"set", "test set", "set label"}:
            set_column = column
        elif name_column is None and re.search(r"name|student", cell, re.IGNORECASE):
            name_column = column
    if not item_columns:
        raise HTTPException(
            status_code=422,
            detail="No item columns found. Use the template: student, set, 1, 2, 3, ...",
        )
    total = test["total_items"]
    extra = sorted(number for number in item_columns if not 1 <= number <= total)
    if extra:
        raise HTTPException(
            status_code=422,
            detail=f"This test has {total} items, but the CSV has item column(s) {', '.join(map(str, extra))}.",
        )
    if name_column is None:
        name_column = next(
            (column for column in range(len(header)) if column not in item_columns.values() and column != set_column),
            None,
        )
    warnings = []
    missing = [number for number in range(1, total + 1) if number not in item_columns]
    if missing:
        warnings.append(f"No column for item(s) {', '.join(map(str, missing))}; counted as unanswered.")
    if len(rows) - 1 > MAX_STUDENTS:
        raise HTTPException(status_code=422, detail=f"Import at most {MAX_STUDENTS} students at a time.")

    students = []
    for row_number, row in enumerate(rows[1:], start=2):
        def cell(column):
            return row[column].strip() if column is not None and column < len(row) else ""

        name = cell(name_column) or f"Student {row_number - 1}"
        if name.casefold().startswith("sample student"):
            continue
        set_label = re.sub(r"(?i)^set\s*", "", cell(set_column)).upper() or "A"
        if set_label not in test["sets"]:
            raise HTTPException(
                status_code=422,
                detail=f"Row {row_number} ({name}) uses Set {set_label}, but this test has "
                f"Set {' and '.join(sorted(test['sets']))} only.",
            )
        answers = []
        score = 0
        for number, entry in enumerate(test["sets"][set_label], start=1):
            item = test["items"][entry["item"]]
            chosen, correct = _grade(item, entry["choices"], cell(item_columns.get(number)))
            answers.append({"item": entry["item"], "chosen": chosen, "correct": correct})
            score += int(correct)
        answers.sort(key=lambda answer: answer["item"])
        students.append({"name": name, "set": set_label, "answers": answers, "score": score})
    if not students:
        raise HTTPException(status_code=422, detail="The CSV has no student rows.")
    return students, warnings


@checks(
    expected="Imported class results",
    probable_cause="The results CSV could not be read or saved",
)
def import_results(test_id: str, content: bytes) -> dict:
    test = load_test(test_id)
    students, warnings = parse_results(test, content)
    with connect() as db:
        db.execute("DELETE FROM assessment_results WHERE test_id=?", (test_id,))
        db.executemany(
            "INSERT INTO assessment_results(id, test_id, student_name, set_label, answers, score) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            [
                (str(uuid.uuid4()), test_id, student["name"], student["set"],
                 json.dumps(student["answers"]), student["score"])
                for student in students
            ],
        )
    return {
        "test_id": test_id,
        "students": len(students),
        "sets": dict(Counter(student["set"] for student in students)),
        "warnings": warnings,
    }


def difficulty_label(p: float) -> str:
    if p >= 0.81:
        return "Very easy"
    if p >= 0.61:
        return "Easy"
    if p >= 0.41:
        return "Average"
    if p >= 0.21:
        return "Difficult"
    return "Very difficult"


def discrimination_label(d: float) -> str:
    if d >= 0.40:
        return "Very good"
    if d >= 0.30:
        return "Good"
    if d >= 0.20:
        return "Fair"
    if d >= 0:
        return "Poor"
    return "Negative"


def decision(p: float, d: float) -> str:
    """Retain good items, revise borderline ones, discard items that don't separate
    students who know the material from those who don't."""
    if d < 0.20:
        return "Discard"
    if d < 0.30 or p < 0.21 or p > 0.80:
        return "Revise"
    return "Retain"


def kr20(item_p: Sequence[float], scores: Sequence[int]) -> float | None:
    k = len(item_p)
    if k < 2 or len(scores) < 2:
        return None
    variance = statistics.pvariance(scores)
    if variance == 0:
        return None
    return round((k / (k - 1)) * (1 - sum(p * (1 - p) for p in item_p) / variance), 3)


def reliability_label(value: float | None) -> str:
    if value is None:
        return "Not enough variation to measure"
    if value >= 0.90:
        return "Excellent"
    if value >= 0.80:
        return "Good"
    if value >= 0.70:
        return "Acceptable"
    if value >= 0.60:
        return "Questionable"
    return "Poor"


def _load_students(test_id: str) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT student_name, set_label, answers, score FROM assessment_results "
            "WHERE test_id=? ORDER BY rowid",
            (test_id,),
        ).fetchall()
    return [
        {"name": row["student_name"], "set": row["set_label"],
         "answers": json.loads(row["answers"]), "score": row["score"]}
        for row in rows
    ]


@checks(
    expected="Item analysis",
    probable_cause="Item analysis could not be calculated",
)
def analyze(test_id: str) -> dict:
    test = load_test(test_id)
    students = _load_students(test_id)
    if len(students) < 2:
        raise HTTPException(
            status_code=422,
            detail="Import at least 2 students' answers to run item analysis.",
        )
    n = len(students)
    group_size = max(1, round(GROUP_SHARE * n))
    ranked = sorted(students, key=lambda student: (-student["score"], student["name"].casefold()))
    upper, lower = ranked[:group_size], ranked[-group_size:]
    set_a_number = {entry["item"]: number for number, entry in enumerate(test["sets"]["A"], start=1)}

    def answer_of(student, index):
        return student["answers"][index]

    items = []
    for index, item in enumerate(test["items"]):
        correct = sum(answer_of(student, index)["correct"] for student in students)
        upper_correct = sum(answer_of(student, index)["correct"] for student in upper)
        lower_correct = sum(answer_of(student, index)["correct"] for student in lower)
        p = correct / n
        d = (upper_correct - lower_correct) / group_size
        entry = {
            "number": set_a_number[index],
            "question_text": item["question_text"],
            "question_type": item["question_type"],
            "topic": item["topic"],
            "correct_answer": item["correct_answer"],
            "correct_count": correct,
            "upper_correct": upper_correct,
            "lower_correct": lower_correct,
            "difficulty_index": round(p, 3),
            "difficulty": difficulty_label(p),
            "discrimination_index": round(d, 3),
            "discrimination": discrimination_label(d),
            "decision": decision(p, d),
            "unanswered": sum(answer_of(student, index)["chosen"] is None for student in students),
        }
        if item["question_type"] == "Multiple Choice":
            picks = Counter(answer_of(student, index)["chosen"] for student in students)
            upper_picks = Counter(answer_of(student, index)["chosen"] for student in upper)
            lower_picks = Counter(answer_of(student, index)["chosen"] for student in lower)
            options = []
            for choice in item["choices"]:
                is_key = choice == item["correct_answer"]
                flag = None
                if not is_key and picks[choice] == 0:
                    flag = "Nobody chose this distractor; replace it."
                elif not is_key and upper_picks[choice] > lower_picks[choice]:
                    flag = "More top students chose this than low students; check if it is also correct."
                options.append({
                    "choice": choice,
                    "is_answer": is_key,
                    "chosen_by": picks[choice],
                    "upper": upper_picks[choice],
                    "lower": lower_picks[choice],
                    "flag": flag,
                })
            entry["options"] = options
        items.append(entry)
    items.sort(key=lambda entry: entry["number"])

    scores = [student["score"] for student in students]
    reliability = kr20([entry["difficulty_index"] for entry in items], scores)
    topics: dict[str, list[float]] = {}
    for entry in items:
        topics.setdefault(entry["topic"], []).append(entry["difficulty_index"])
    topic_summary = sorted(
        (
            {"topic": topic, "items": len(values), "average_difficulty_index": round(sum(values) / len(values), 3)}
            for topic, values in topics.items()
        ),
        key=lambda row: (row["average_difficulty_index"], row["topic"].casefold()),
    )
    total = test["total_items"]
    warnings = []
    if n < FEW_STUDENTS:
        warnings.append(
            f"Only {n} students: with fewer than {FEW_STUDENTS}, these indices are rough estimates."
        )
    return {
        "test_id": test_id,
        "title": test["title"],
        "summary": {
            "students": n,
            "items": total,
            "group_size": group_size,
            "mean_score": round(statistics.mean(scores), 2),
            "median_score": statistics.median(scores),
            "standard_deviation": round(statistics.pstdev(scores), 2),
            "highest_score": max(scores),
            "lowest_score": min(scores),
            "mean_percent": round(100 * statistics.mean(scores) / total, 1) if total else 0.0,
            "kr20": reliability,
            "reliability": reliability_label(reliability),
            "decisions": dict(Counter(entry["decision"] for entry in items)),
        },
        "items": items,
        "topics": topic_summary,
        "students": [
            {"name": student["name"], "set": student["set"], "score": student["score"]}
            for student in ranked
        ],
        "warnings": warnings,
        "method": {
            "difficulty_index": "Students who answered correctly ÷ all students.",
            "discrimination_index": (
                f"(Correct in top {round(GROUP_SHARE * 100)}% − correct in bottom "
                f"{round(GROUP_SHARE * 100)}%) ÷ students per group ({group_size})."
            ),
            "decision": "Discard if D < 0.20; Revise if D < 0.30 or p is outside 0.21–0.80; otherwise Retain.",
            "kr20": "KR-20 = k/(k−1) × (1 − Σpq ÷ variance of total scores).",
        },
    }
