from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from .definitions import _DISTRACTOR_JUNK, _PRONOUNS, _definition_category, _definition_headword

def rank_distractors(
    answer: str,
    definition_records: Sequence[Mapping],
) -> list[Mapping]:
    answer_key = re.sub(r"\s+", " ", answer).strip().casefold()
    answer_words = len(answer_key.split())
    answer_length = len(answer_key)
    unique: dict[str, Mapping] = {}
    for record in definition_records:
        normalized = re.sub(r"\s+", " ", str(record.get("term", ""))).strip()
        key = normalized.casefold()
        if normalized and key != answer_key:
            unique.setdefault(key, record)
    return sorted(
        unique.values(),
        key=lambda record: (
            abs(
                len(re.sub(r"\s+", " ", str(record.get("term", ""))).strip().split())
                - answer_words
            ),
            abs(
                len(re.sub(r"\s+", " ", str(record.get("term", ""))).strip())
                - answer_length
            ),
            str(record.get("term", "")).casefold(),
        ),
    )

def _usable_distractor(
    term: str,
    answer: str,
    question: str,
    cited_passage: str,
    other_answers: set[str],
    source_defined_terms: Sequence[str] = (),
) -> bool:
    normalized = re.sub(r"\s+", " ", term).strip().casefold()
    words = re.findall(r"[a-z0-9]+", normalized)
    if (
        len(normalized) < 3
        or not words
        or normalized in _DISTRACTOR_JUNK
        or len(words) == 1 and words[0] in _DISTRACTOR_JUNK
        or any(word in _PRONOUNS for word in words)
        or normalized == answer.casefold()
        or normalized in other_answers
        or (
            normalized not in {
                re.sub(r"\s+", " ", str(item)).strip().casefold()
                for item in source_defined_terms
            }
            and (
                normalized in question.casefold()
                or re.search(
                    rf"(?<!\w){re.escape(normalized)}(?!\w)",
                    cited_passage.casefold(),
                )
            )
        )
    ):
        return False
    return True

def _distractor_matches_stem_category(
    question: str,
    explanation: str,
    term: str = "",
) -> bool:
    example_stem = re.search(
        r"\ban example of\s+(.+?)\?\s*$",
        question,
        re.IGNORECASE,
    )
    if example_stem:
        target = re.sub(
            r"^(?:a|an|the)\s+",
            "",
            example_stem.group(1).strip().casefold(),
        )
        return bool(
            re.search(
                rf"\bexamples?\s+of\s+(?:an?\s+|the\s+)?{re.escape(target)}\b",
                explanation,
                re.IGNORECASE,
            )
        )
    stem_category = re.search(
            r"\b(?:describes|refers to|identifies)\s+(?:(?:an?|the)\s+)?(.+?)"
        r"(?:\s+(?:that|which|who|in which|where|when)\b|\?|$)",
        question,
        re.IGNORECASE,
    )
    if not stem_category:
        return False
    phrase = stem_category.group(1).strip().casefold()
    category = _definition_headword(phrase)
    distractor_category = _definition_category(explanation)
    if re.search(r"\bphysical\s+components?\b", phrase):
        return distractor_category in {"physical_component", "storage_technology"}
    if category == "hardware":
        return distractor_category in {"physical_component", "storage_technology"}
    if category in {"interface", "framework", "unit"}:
        return category in {
            _definition_headword(explanation),
            distractor_category,
        }
    if category == "device":
        return (
            _definition_headword(explanation) == "device"
            or "device" in term.casefold().split()
        )
    if category == "organization":
        return distractor_category == "organization"
    return False

def _similar_definition_term(answer: str, distractor: str) -> bool:
    answer_words = re.findall(r"[A-Za-z0-9]+", answer)
    distractor_words = re.findall(r"[A-Za-z0-9]+", distractor)
    return (
        abs(len(answer_words) - len(distractor_words)) <= 1
        and abs(len(answer) - len(distractor)) <= max(16, len(answer) // 2)
    )
