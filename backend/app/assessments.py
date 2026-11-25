"""Teacher tools: build a test from lessons with a Table of Specifications (TOS),
make a shuffled Set B, and export the test, answer key and TOS as Word files.

How a test is built, in plain terms:
1. Generate every question the lessons can support (all selected question types).
2. Count how many lesson passages belong to each topic; that share is the topic's weight.
3. Split the total number of items by those weights (largest-remainder rounding,
   never giving a topic more items than it has questions).
4. Inside each topic, take the best questions, alternating question types, and never
   test the same source sentence twice.
"""
from __future__ import annotations

import importlib
import io
import json
import math
import random
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from fastapi import HTTPException

from .core.checks import checks
from .database import connect

QUESTION_TYPE_ORDER = ("Multiple Choice", "True or False", "Identification")
SECTION_DIRECTIONS = {
    "Multiple Choice": "Choose the letter of the correct answer.",
    "True or False": "Write TRUE if the statement is correct and FALSE if it is not.",
    "Identification": "Write the term that matches each description.",
}
ROMAN = ("I", "II", "III", "IV", "V")
LETTERS = "ABCDEFGH"
POOL_PER_TYPE = 50
# Every generated question is a recall/definition item; the TOS says so honestly.
COGNITIVE_LEVEL = "Remembering"


def _compat_main():
    return importlib.import_module("app.main")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def explanation_for(question: Mapping) -> str:
    """The full source sentence behind a question, for showing after it is answered."""
    cited = str(question.get("cited_passage") or "").strip()
    if cited:
        return cited
    reference = str(question.get("source_reference") or "")
    match = re.search(r"Source Text/Reference:\s*(.+)", reference, re.DOTALL)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return str(question.get("support_excerpt") or question.get("explanation") or "").strip()


def concept_key(question: Mapping) -> str:
    """Questions made from the same source sentence test the same thing."""
    text = explanation_for(question) or str(question.get("question_text", ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def allocate_items(
    weights: Mapping[str, float],
    available: Mapping[str, int],
    total: int,
) -> dict[str, int]:
    """Split `total` items across topics in proportion to `weights`.

    Uses largest-remainder rounding so the counts add up exactly, and never gives a
    topic more items than it has questions. Topics with zero weight only receive
    items when the weighted topics run out of questions.
    """
    allocation = {topic: 0 for topic in available}
    target = min(int(total), sum(max(0, count) for count in available.values()))

    def fill(topics: list[str], topic_weights: Mapping[str, float]) -> None:
        active = [topic for topic in topics if allocation[topic] < available[topic]]
        while active:
            remaining = target - sum(allocation.values())
            if remaining <= 0:
                return
            weight_sum = sum(topic_weights[topic] for topic in active)
            quotas = {
                topic: remaining * (topic_weights[topic] / weight_sum if weight_sum else 1 / len(active))
                for topic in active
            }
            for topic in active:
                room = available[topic] - allocation[topic]
                allocation[topic] += min(math.floor(quotas[topic]), room)
            remaining = target - sum(allocation.values())
            ranked = sorted(
                active,
                key=lambda topic: (
                    -(quotas[topic] - math.floor(quotas[topic])),
                    -topic_weights[topic],
                    topic.casefold(),
                ),
            )
            for topic in ranked:
                if remaining <= 0:
                    break
                if allocation[topic] < available[topic]:
                    allocation[topic] += 1
                    remaining -= 1
            active = [topic for topic in active if allocation[topic] < available[topic]]

    weighted = [topic for topic in available if weights.get(topic, 0) > 0]
    fill(weighted, {topic: float(weights.get(topic, 0)) for topic in available})
    unweighted = [topic for topic in available if topic not in weighted]
    fill(unweighted, {topic: float(available[topic]) for topic in available})
    return allocation


def _rank_key(question: Mapping) -> tuple:
    return (
        -float(question.get("likelihood_score") or 0.0),
        -float(question.get("priority_score") or 0.0),
        -float(question.get("confidence_score") or 0.0),
        str(question.get("question_text", "")),
    )


def select_items(
    pool: Sequence[Mapping],
    allocation: Mapping[str, int],
    question_types: Sequence[str],
) -> list[dict]:
    """Pick each topic's questions, alternating question types, one per source sentence."""
    used: set[str] = set()
    chosen: list[dict] = []
    for topic, count in allocation.items():
        by_type = {
            question_type: sorted(
                (item for item in pool if item["topic"] == topic and item["question_type"] == question_type),
                key=_rank_key,
            )
            for question_type in question_types
        }
        picked = 0
        while picked < count and any(by_type.values()):
            for question_type in question_types:
                candidates = by_type[question_type]
                while candidates and concept_key(candidates[0]) in used:
                    candidates.pop(0)
                if not candidates or picked >= count:
                    continue
                item = candidates.pop(0)
                used.add(concept_key(item))
                chosen.append(dict(item))
                picked += 1
    return chosen


def _distinct_concepts_by_topic(pool: Sequence[Mapping]) -> dict[str, int]:
    concepts: dict[str, set[str]] = {}
    for item in pool:
        concepts.setdefault(item["topic"], set()).add(concept_key(item))
    return {topic: len(keys) for topic, keys in concepts.items()}


def _answer_letter(choices: Sequence[str], answer: str) -> str:
    for index, choice in enumerate(choices):
        if choice == answer:
            return LETTERS[index]
    return ""


def arrange_sets(items: Sequence[Mapping], test_id: str, include_set_b: bool) -> dict:
    """Set A keeps the built order. Set B shuffles items within each section and
    shuffles multiple-choice options, using a fixed seed so it never changes."""
    sets = {"A": [{"item": index, "choices": list(item["choices"])} for index, item in enumerate(items)]}
    if include_set_b:
        rng = random.Random(f"{test_id}:B")
        order: list[int] = []
        for question_type in QUESTION_TYPE_ORDER:
            section = [index for index, item in enumerate(items) if item["question_type"] == question_type]
            rng.shuffle(section)
            order.extend(section)
        entries = []
        for index in order:
            choices = list(items[index]["choices"])
            rng.shuffle(choices)
            entries.append({"item": index, "choices": choices})
        sets["B"] = entries
    return sets


def answer_key(test: Mapping, set_label: str) -> list[dict]:
    key = []
    for number, entry in enumerate(test["sets"][set_label], start=1):
        item = test["items"][entry["item"]]
        answer = item["correct_answer"]
        letter = _answer_letter(entry["choices"], answer) if entry["choices"] else ""
        key.append({
            "number": number,
            "answer": letter or (answer.upper() if item["question_type"] == "True or False" else answer),
            "answer_text": answer,
        })
    return key


def _sections(test: Mapping, set_label: str) -> list[dict]:
    sections = []
    for number, entry in enumerate(test["sets"][set_label], start=1):
        item = test["items"][entry["item"]]
        if not sections or sections[-1]["question_type"] != item["question_type"]:
            sections.append({"question_type": item["question_type"], "items": []})
        sections[-1]["items"].append({"number": number, "item": item, "choices": entry["choices"]})
    return sections


def _read_lessons(db, lesson_ids: Sequence[str]) -> tuple[list[dict], dict]:
    main = _compat_main()
    sources = []
    features = {"emphasized_terms": [], "heading_terms": [], "list_terms": []}
    for lesson_id in lesson_ids:
        row = db.execute(
            "SELECT id, name, stored_path FROM uploads WHERE id=?", (lesson_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="A selected lesson was not found.")
        path = Path(row["stored_path"]).resolve()
        if path.parent != main.UPLOADS.resolve():
            raise HTTPException(status_code=500, detail="The saved lesson path is invalid.")
        try:
            content = path.read_bytes()
        except OSError as error:
            raise HTTPException(status_code=500, detail=f"Could not read lesson {row['name']}.") from error
        text = main.extract_text(row["name"], content)
        lesson_features = main.extract_lesson_features(row["name"], content)
        for key in features:
            features[key].extend(lesson_features.get(key, []))
        sources.append({"id": row["id"], "name": row["name"], "text": text, "kind": "lesson"})
    return sources, features


def _read_dataset(db, dataset_id: str) -> tuple[str, list[tuple[str, str]]]:
    main = _compat_main()
    if dataset_id == "builtin":
        return "Built-in examples", list(main.BUILTIN_TRAINING_EXAMPLES)
    dataset = db.execute("SELECT name FROM training_datasets WHERE id=?", (dataset_id,)).fetchone()
    if not dataset:
        raise HTTPException(status_code=404, detail="Training dataset not found.")
    rows = db.execute(
        "SELECT text, topic FROM training_examples WHERE dataset_id=? ORDER BY rowid", (dataset_id,)
    ).fetchall()
    return dataset["name"], [(row["text"], row["topic"]) for row in rows]


def _public_item(item: Mapping, index: int) -> dict:
    return {
        "index": index,
        "question_id": item["id"],
        "question_type": item["question_type"],
        "question_text": item["question_text"],
        "choices": list(item.get("choices") or []),
        "correct_answer": item["correct_answer"],
        "topic": item["topic"],
        "cognitive_level": COGNITIVE_LEVEL,
        "likelihood": item.get("likelihood"),
        "source_material_name": item.get("source_material_name", ""),
        "explanation": explanation_for(item),
    }


def _specification(
    topics: Sequence[str],
    passages: Mapping[str, int],
    available: Mapping[str, int],
    allocation: Mapping[str, int],
    items: Sequence[Mapping],
) -> dict:
    total_passages = sum(passages.get(topic, 0) for topic in topics)
    total_items = len(items)
    numbers: dict[str, list[int]] = {}
    for number, item in enumerate(items, start=1):
        numbers.setdefault(item["topic"], []).append(number)
    rows = []
    for topic in topics:
        count = allocation.get(topic, 0)
        rows.append({
            "topic": topic,
            "lesson_passages": passages.get(topic, 0),
            "weight_percent": round(100 * passages.get(topic, 0) / total_passages, 1) if total_passages else 0.0,
            "questions_available": available.get(topic, 0),
            "items": count,
            "percent_of_test": round(100 * count / total_items, 1) if total_items else 0.0,
            "item_numbers": numbers.get(topic, []),
            "cognitive_levels": {COGNITIVE_LEVEL: count} if count else {},
        })
    return {
        "rows": rows,
        "totals": {
            "lesson_passages": total_passages,
            "items": total_items,
            "questions_available": sum(available.values()),
        },
        "cognitive_levels": [COGNITIVE_LEVEL],
        "method": (
            "Each topic's weight is its share of the lesson passages. Items are split by "
            "that weight with largest-remainder rounding, capped by how many different "
            "questions the lessons support for the topic. Item numbers are for Set A."
        ),
    }


@checks(
    expected="Built test with Table of Specifications",
    probable_cause="The test could not be built from the selected lessons",
)
def build_test(
    *,
    title: str,
    training_dataset_id: str,
    lesson_upload_ids: Sequence[str],
    total_items: int,
    question_types: Sequence[str],
    items_per_topic: Mapping[str, int] | None = None,
    include_set_b: bool = True,
    random_seed: int | None = None,
) -> dict:
    main = _compat_main()
    lesson_ids = list(dict.fromkeys(lesson_upload_ids))
    question_types = [kind for kind in QUESTION_TYPE_ORDER if kind in set(question_types)]
    if not question_types:
        raise HTTPException(status_code=422, detail="Choose at least one question type.")
    with connect() as db:
        dataset_name, examples = _read_dataset(db, training_dataset_id)
        sources, features = _read_lessons(db, lesson_ids)
    policy = main.get_decision_policy({"id": training_dataset_id, "examples": examples})
    metrics: dict = {}
    seed = random_seed if random_seed is not None else uuid.uuid4().int
    pool: list[dict] = []
    for question_type in question_types:
        try:
            result = main.generate_questions(
                requested_count=POOL_PER_TYPE,
                question_type=question_type,
                difficulty="Moderate",
                topic_filter="All Topics",
                per_topic=POOL_PER_TYPE,
                training_examples=examples,
                dataset_id=training_dataset_id,
                dataset_name=dataset_name,
                sources=sources,
                lesson_mode=True,
                training_metrics=metrics,
                allow_repeats=True,
                random_seed=seed,
                decision_policy=policy,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        pool.extend(result["questions"])
    if not pool:
        raise HTTPException(
            status_code=422,
            detail="These lessons did not produce any questions. Try another lesson or question type.",
        )
    ranking = main.rank_lesson_likelihood(
        pool,
        "\n\n".join(source["text"] for source in sources),
        examples,
        emphasized_terms=features["emphasized_terms"],
        heading_terms=features["heading_terms"],
        list_terms=features["list_terms"],
        training_metrics=metrics,
        dataset_id=training_dataset_id,
        decision_policy=policy,
    )
    passages = Counter(
        passage["topic"] for passage in ranking.get("lesson_analysis", {}).get("passages", [])
    )
    available = _distinct_concepts_by_topic(pool)
    if items_per_topic:
        unknown = sorted(set(items_per_topic) - set(available))
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"These topics have no questions in the lessons: {', '.join(unknown)}.",
            )
        allocation = {
            topic: max(0, min(int(items_per_topic.get(topic, 0)), available[topic]))
            for topic in available
        }
    else:
        allocation = allocate_items(passages, available, total_items)
    topic_order = sorted(available, key=lambda topic: (-passages.get(topic, 0), -available[topic], topic.casefold()))
    allocation = {topic: allocation.get(topic, 0) for topic in topic_order}
    selected = select_items(pool, allocation, question_types)
    if not selected:
        raise HTTPException(status_code=422, detail="Give at least one topic one item.")
    position = {topic: index for index, topic in enumerate(topic_order)}
    selected.sort(key=lambda item: (QUESTION_TYPE_ORDER.index(item["question_type"]), position[item["topic"]]))
    requested = sum(allocation.values()) if items_per_topic else int(total_items)
    warnings = []
    if len(selected) < requested:
        warnings.append(
            f"Only {len(selected)} different questions could be made from these lessons "
            f"(you asked for {requested})."
        )
    if available.get("Unclassified"):
        warnings.append(
            "Some questions are Unclassified. A training dataset made for this course gives a clearer TOS."
        )

    test_id = str(uuid.uuid4())
    items = [_public_item(item, index) for index, item in enumerate(selected)]
    test = {
        "id": test_id,
        "title": title.strip() or f"{', '.join(source['name'] for source in sources)} Test",
        "created_at": _stamp(),
        "lesson_names": [source["name"] for source in sources],
        "training_dataset_name": dataset_name,
        "question_types": question_types,
        "total_items": len(items),
        "items": items,
        "specification": _specification(topic_order, passages, available, allocation, items),
        "warnings": warnings,
    }
    test["sets"] = arrange_sets(items, test_id, include_set_b)
    with connect() as db:
        db.execute(
            "INSERT INTO assessment_tests(id, title, created_at, details) VALUES(?, ?, ?, ?)",
            (test_id, test["title"], test["created_at"], json.dumps(test)),
        )
    return with_answer_keys(test)


def with_answer_keys(test: Mapping) -> dict:
    return {**test, "answer_keys": {label: answer_key(test, label) for label in test["sets"]}}


def load_test(test_id: str) -> dict:
    with connect() as db:
        row = db.execute("SELECT details FROM assessment_tests WHERE id=?", (test_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Test not found.")
    return json.loads(row["details"])


def list_tests() -> dict:
    with connect() as db:
        rows = db.execute(
            "SELECT t.id, t.title, t.created_at, t.details, "
            "(SELECT COUNT(*) FROM assessment_results r WHERE r.test_id=t.id) AS students "
            "FROM assessment_tests t ORDER BY t.created_at DESC, t.rowid DESC"
        ).fetchall()
    tests = []
    for row in rows:
        details = json.loads(row["details"])
        tests.append({
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "total_items": details["total_items"],
            "question_types": details["question_types"],
            "lesson_names": details["lesson_names"],
            "sets": sorted(details["sets"]),
            "students": row["students"],
        })
    return {"tests": tests}


def rename_test(test_id: str, title: str) -> dict:
    title = title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Test title cannot be blank.")
    test = load_test(test_id)
    test["title"] = title
    with connect() as db:
        db.execute(
            "UPDATE assessment_tests SET title=?, details=? WHERE id=?",
            (title, json.dumps(test), test_id),
        )
    return {"id": test_id, "title": title}


def delete_test(test_id: str) -> dict:
    with connect() as db:
        if db.execute("DELETE FROM assessment_tests WHERE id=?", (test_id,)).rowcount == 0:
            raise HTTPException(status_code=404, detail="Test not found.")
    return {"deleted": test_id}


# ---------- Word exports ----------

def _new_document():
    from docx import Document
    from docx.shared import Pt

    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    return document


def _to_bytes(document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def export_test_paper(test: Mapping, set_label: str) -> bytes:
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    document = _new_document()
    heading = document.add_heading(test["title"], level=1)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if len(test["sets"]) > 1:
        label = document.add_paragraph(f"Set {set_label}")
        label.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph(
        "Name: ______________________________   Section: ____________\n"
        "Date: ____________________   Score: ______ / " + str(test["total_items"])
    )
    for section_index, section in enumerate(_sections(test, set_label)):
        question_type = section["question_type"]
        document.add_heading(
            f"Test {ROMAN[section_index]}. {question_type}", level=2
        )
        document.add_paragraph(f"Directions: {SECTION_DIRECTIONS[question_type]}")
        for entry in section["items"]:
            item = entry["item"]
            if question_type == "Multiple Choice":
                document.add_paragraph(f"{entry['number']}. {item['question_text']}")
                for index, choice in enumerate(entry["choices"]):
                    document.add_paragraph(f"{LETTERS[index]}. {choice}", style="List Continue")
            else:
                document.add_paragraph(f"__________ {entry['number']}. {item['question_text']}")
    return _to_bytes(document)


def export_answer_key(test: Mapping) -> bytes:
    document = _new_document()
    document.add_heading(f"{test['title']} — Answer Key", level=1)
    labels = sorted(test["sets"])
    keys = {label: answer_key(test, label) for label in labels}
    table = document.add_table(rows=1, cols=1 + len(labels))
    table.style = "Table Grid"
    table.rows[0].cells[0].text = "No."
    for column, label in enumerate(labels, start=1):
        table.rows[0].cells[column].text = f"Set {label}"
    for row_index in range(test["total_items"]):
        cells = table.add_row().cells
        cells[0].text = str(row_index + 1)
        for column, label in enumerate(labels, start=1):
            cells[column].text = keys[label][row_index]["answer"]
    return _to_bytes(document)


def export_specification(test: Mapping) -> bytes:
    from docx.enum.section import WD_ORIENT

    document = _new_document()
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = section.page_height, section.page_width
    document.add_heading(f"{test['title']} — Table of Specifications", level=1)
    document.add_paragraph("Lessons: " + ", ".join(test["lesson_names"]))
    headers = [
        "Topic", "Lesson passages", "Weight (%)", "No. of items",
        "% of test", COGNITIVE_LEVEL, "Item placement (Set A)",
    ]
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for column, header in enumerate(headers):
        table.rows[0].cells[column].text = header
    specification = test["specification"]
    for row in specification["rows"]:
        if not row["items"]:
            continue
        cells = table.add_row().cells
        values = [
            row["topic"], str(row["lesson_passages"]), f"{row['weight_percent']:g}",
            str(row["items"]), f"{row['percent_of_test']:g}",
            str(row["cognitive_levels"].get(COGNITIVE_LEVEL, 0)),
            _number_ranges(row["item_numbers"]),
        ]
        for column, value in enumerate(values):
            cells[column].text = value
    total = table.add_row().cells
    total[0].text = "Total"
    total[1].text = str(specification["totals"]["lesson_passages"])
    total[2].text = "100"
    total[3].text = str(specification["totals"]["items"])
    total[4].text = "100"
    total[5].text = str(specification["totals"]["items"])
    document.add_paragraph()
    document.add_paragraph(specification["method"])
    return _to_bytes(document)


def _number_ranges(numbers: Sequence[int]) -> str:
    """[1, 2, 3, 7, 9, 10] -> "1-3, 7, 9-10"."""
    parts: list[str] = []
    for number in sorted(numbers):
        if parts and "-" not in parts[-1].split(",")[-1] and int(parts[-1]) == number - 1:
            parts[-1] = f"{parts[-1]}-{number}"
        elif parts and "-" in parts[-1] and int(parts[-1].split("-")[1]) == number - 1:
            parts[-1] = f"{parts[-1].split('-')[0]}-{number}"
        else:
            parts.append(str(number))
    return ", ".join(parts)
