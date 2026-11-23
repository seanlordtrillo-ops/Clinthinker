from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
_HEADER_FIELD_LINE = re.compile(
    r"^\s*(?:student\s+)?(?:name|section|course(?:\s+(?:name|code|number))?|"
    r"class|date|instructor|teacher|student\s*(?:id|number)|id)"
    r"\b\s*(?::|#|-|_{2,})",
    re.IGNORECASE,
)
_EXAM_TITLE_LINE = re.compile(
    r"^\s*(?:(?:midterm|final)\s+)?(?:exam|quiz|test|midterm|final)"
    r"\s*(?:(?:no\.?|#)\s*)?(?:\d+|[ivxlcdm]+)?"
    r"(?:\s*[-:|]\s*[\w &-]+)?\s*$",
    re.IGNORECASE,
)
_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:page\s+)?\d+\s*(?:of\s+\d+|/\s*\d+)?\s*$",
    re.IGNORECASE,
)

def split_sentences(text: str) -> list[str]:
    return [
        sentence.strip(" \t-•")
        for sentence in _SENTENCE_END.split(text)
        if 24 <= len(sentence.strip(" \t-•")) <= 500
    ]

def strip_document_headers(text: str) -> tuple[str, int]:
    content_lines = []
    removed_lines = 0
    for line in text.splitlines():
        stripped = line.strip()
        if (
            not stripped
            or _HEADER_FIELD_LINE.match(stripped)
            or _EXAM_TITLE_LINE.match(stripped)
            or _PAGE_NUMBER_LINE.match(stripped)
        ):
            if stripped:
                removed_lines += 1
            continue
        content_lines.append(line)
    return "\n".join(content_lines), removed_lines
