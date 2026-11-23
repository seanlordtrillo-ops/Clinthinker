from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence

from .question_quality import clean_statement
from .distractors import _usable_distractor, _similar_definition_term
from .definitions import _is_concept_term
from .true_false import _negate_statement

DEFAULT_PRIORITY_WEIGHTS = {"historical_frequency": 0.40, "course_importance": 0.30, "model_confidence": 0.20, "recent_occurrence": 0.10}
QUESTION_TYPES = {"Multiple Choice", "True or False", "Identification"}
DIFFICULTIES = {"Easy", "Moderate", "Difficult"}

def validate_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    values = dict(DEFAULT_PRIORITY_WEIGHTS if weights is None else weights)
    if set(values) != set(DEFAULT_PRIORITY_WEIGHTS):
        raise ValueError("Priority weights must include all four supported score components.")
    if any(
        not isinstance(value, (float, int))
        or not math.isfinite(value)
        or value < 0
        for value in values.values()
    ):
        raise ValueError("Priority weights must be non-negative numbers.")
    total = sum(values.values())
    if abs(total - 1.0) > 0.001:
        raise ValueError("Priority weights must add up to 1.0.")
    return {key: float(value) for key, value in values.items()}

def validate_candidate(
    candidate: Mapping,
    question_type: str,
    other_correct_answers: Sequence[str] = (),
) -> bool:
    question = str(candidate.get("question_text", "")).strip()
    answer = str(candidate.get("correct_answer", "")).strip()
    source = str(candidate.get("source_reference", "")).strip()
    excerpt = str(candidate.get("support_excerpt", "")).strip()
    cited_passage = re.sub(
        r"\s+", " ", str(candidate.get("cited_passage", "")).strip()
    )
    cited_folded = cited_passage.casefold()
    if (
        question_type not in QUESTION_TYPES
        or candidate.get("difficulty") not in DIFFICULTIES
        or not candidate.get("topic")
        or not answer
        or not source
        or not excerpt
        or not cited_passage
        or not 24 <= len(question) <= 1000
        or re.search(
            r"\b(?:this passage|the text above|according to the passage)\b",
            question,
            re.IGNORECASE,
        )
        or cited_passage.casefold() in re.sub(r"\s+", " ", question).casefold()
        or cited_passage.casefold() not in re.sub(r"\s+", " ", source).casefold()
        or excerpt.casefold() not in str(candidate.get("source_content", "")).casefold()
        or cited_folded not in re.sub(
            r"\s+", " ", str(candidate.get("source_content", ""))
        ).casefold()
    ):
        return False
    choices = candidate.get("choices", [])
    if question_type == "Multiple Choice":
        normalized = [
            re.sub(r"\s+", " ", str(choice)).strip().casefold()
            for choice in choices
        ]
        wrong_choices = [
            str(choice).strip()
            for choice in choices
            if str(choice).strip().casefold() != answer.casefold()
        ]
        other_answers = {
            re.sub(r"\s+", " ", str(item)).strip().casefold()
            for item in other_correct_answers
        }
        return (
            len(normalized) == 4
            and all(normalized)
            and len(set(normalized)) == 4
            and _is_concept_term(answer)
            and all(_is_concept_term(choice) for choice in choices)
            and answer.casefold() in normalized
            and re.search(
                rf"(?<!\w){re.escape(answer.casefold())}(?!\w)", cited_folded
            ) is not None
            and all(
                _usable_distractor(
                    choice,
                    answer,
                    question,
                    cited_passage,
                    other_answers,
                    candidate.get("source_defined_terms", ()),
                )
                for choice in wrong_choices
            )
            and all(
                candidate.get("topic") == "Unclassified"
                or _similar_definition_term(answer, choice)
                for choice in wrong_choices
            )
        )
    if question_type == "Identification":
        return (
            not choices
            and re.search(
                rf"(?<!\w){re.escape(answer.casefold())}(?!\w)", cited_folded
            ) is not None
        )
    if choices or answer not in {"True", "False"}:
        return False
    supported_statement = str(candidate.get("supported_statement", "")).strip()
    if not supported_statement or clean_statement(supported_statement) != supported_statement:
        return False
    if answer == "True":
        return question == supported_statement
    false_statement = str(candidate.get("false_statement", "")).strip()
    false_basis = str(candidate.get("false_basis") or "").strip()
    if false_statement:
        if false_basis:
            return (
                question == false_statement
                and clean_statement(false_statement) == false_statement
                and false_basis.casefold()
                in str(candidate.get("source_content", "")).casefold()
            )
        expected_statement = clean_statement(
            _negate_statement(supported_statement) or ""
        )
        return bool(
            expected_statement
            and false_statement == expected_statement
            and question == false_statement
        )
    expected_statement = clean_statement(_negate_statement(supported_statement) or "")
    return bool(expected_statement and question == expected_statement)
