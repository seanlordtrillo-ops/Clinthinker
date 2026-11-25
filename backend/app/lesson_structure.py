"""Finds the heading each lesson sentence sits under.

Lessons list related terms under one heading, for example "Testing levels" followed by
"Unit testing — …", "Integration testing — …". Knowing the heading lets the generator
(1) take wrong answers from the same list, so every choice is the same kind of thing,
and (2) give the question context, such as: Under "Testing levels", which term …?
"""
from __future__ import annotations

import re
from typing import Sequence

_TERMINAL = (".", "!", "?", ":", ";", ",")
_NUMBERING = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s*$")
_NUMBER_PREFIX = re.compile(r"^\s*\d+(?:\.\d+)*[.)]?\s+")
_PAGE_FOOTER = re.compile(r"\bpage\s+\d+\s*$", re.IGNORECASE)
MAX_HEADING_WORDS = 12
LONG_LINE_WORDS = 12
MAX_PARENTHETICAL = 45


def _outside_parentheses(text: str) -> str:
    return re.sub(r"\([^()]*\)", "", text)


def clean_heading(text: str) -> str:
    return re.sub(r"\s+", " ", _NUMBER_PREFIX.sub("", text)).strip()


def _looks_like_heading(line: str, *, strict: bool = True) -> bool:
    heading = clean_heading(line)
    if not heading or not heading[0].isupper() or line.endswith(_TERMINAL):
        return False
    if not 1 <= len(heading.split()) <= MAX_HEADING_WORDS or not re.search(r"[A-Za-z]{3,}", heading):
        return False
    bare = _outside_parentheses(heading)
    if any(mark in bare for mark in (":", ",", "—", " - ", ";")):
        return False
    if strict and any(len(inner) > MAX_PARENTHETICAL for inner in re.findall(r"\(([^()]*)\)", heading)):
        return False
    return True


def sentence_headings(text: str, raw_sentences: Sequence[str]) -> list[str | None]:
    """For every raw sentence, the closest heading above it (None if there is none).

    A heading must sit on its own line, look like a title, and not continue a long
    unfinished line. Runs of numbered title-like lines ("1. Visibility of system status",
    "2. Match between …") are list items, not headings.
    """
    positions: list[int] = []
    cursor = 0
    for raw in raw_sentences:
        found = text.find(raw, cursor) if raw else -1
        positions.append(found)
        if found >= 0:
            cursor = found + len(raw)

    lines = []  # (index, text) of meaningful lines, skipping page footers
    for index, raw in enumerate(raw_sentences):
        stripped = re.sub(r"\s+", " ", str(raw)).strip()
        if stripped and not _PAGE_FOOTER.search(stripped):
            lines.append((index, stripped))

    candidate: dict[int, bool] = {}
    numbered: dict[int, bool] = {}
    content = [(index, line) for index, line in lines if not _NUMBERING.match(line)]
    content_position = {index: position for position, (index, _) in enumerate(content)}
    for position, (index, line) in enumerate(lines):
        previous_raw = lines[position - 1][1] if position else None
        numbered[index] = bool(previous_raw and _NUMBERING.match(previous_raw))
    for index, line in content:
        start = positions[index]
        line_start = text.rfind("\n", 0, max(start, 0)) + 1
        prefix = text[line_start:start] if start >= 0 else ""
        own_line = start <= 0 or not prefix.strip() or bool(_NUMBERING.match(prefix))
        position = content_position[index]
        previous_index, previous = content[position - 1] if position else (None, None)
        unfinished = bool(previous and not previous.endswith((".", "!", "?", ":")))
        # A short unfinished line right before this one means both are list items,
        # unless that line was itself a numbered item ("10. Help and documentation").
        # A numbered line ("2. Development Methodologies") or a line after a blank line
        # starts a new section even if the line before it was a short title.
        starts_section = numbered.get(index, False) or (
            previous_index is not None
            and positions[previous_index] >= 0
            and start >= 0
            and "\n\n" in text[positions[previous_index] + len(raw_sentences[previous_index]):start]
        )
        follows_list_item = bool(
            unfinished
            and not starts_section
            and _looks_like_heading(previous, strict=False)
            and not numbered.get(previous_index, False)
        )
        continues_long_line = bool(unfinished and len(previous.split()) > LONG_LINE_WORDS)
        candidate[index] = (
            own_line
            and not follows_list_item
            and not continues_long_line
            and _looks_like_heading(line)
        )

    list_items = set()
    numbered_candidates = [index for index, _ in lines if candidate.get(index) and numbered[index]]
    order = {index: position for position, (index, _) in enumerate(lines)}
    for first, second in zip(numbered_candidates, numbered_candidates[1:]):
        if order[second] - order[first] <= 2:
            list_items.update({first, second})

    headings: list[str | None] = []
    current: str | None = None
    for index in range(len(raw_sentences)):
        if candidate.get(index) and index not in list_items:
            current = clean_heading(raw_sentences[index])
            headings.append(None)
        else:
            headings.append(current)
    return headings
