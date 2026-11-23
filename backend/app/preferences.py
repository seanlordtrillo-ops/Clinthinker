from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

def question_preference_features(question: Mapping) -> dict[str, str]:
    text = str(question.get("question_text", "")).strip().casefold()
    word_count = len(text.split())
    question_length = "short" if word_count < 12 else "medium" if word_count < 24 else "long"
    answer_word_count = len(str(question.get("correct_answer", "")).split())
    if text.startswith("true or false:"):
        wording_pattern = "true-or-false"
    elif text.startswith("which of the following"):
        wording_pattern = "which-of-the-following"
    elif text.startswith("what "):
        wording_pattern = "what"
    elif text.startswith("which "):
        wording_pattern = "which"
    elif text.startswith("define "):
        wording_pattern = "define"
    elif text.startswith("identify "):
        wording_pattern = "identify"
    else:
        wording_pattern = "other"
    return {
        "question_type": str(question.get("question_type", "")),
        "difficulty": str(question.get("difficulty", "")),
        "wording_pattern": wording_pattern,
        "question_length": question_length,
        "answer_length": "single-term" if answer_word_count <= 1 else "phrase",
    }

def question_preference_profile(
    feedback: Sequence[Mapping],
) -> dict[tuple[str, str], tuple[int, int]]:
    totals: dict[tuple[str, str], list[int]] = {}
    for entry in feedback:
        for feature, value in question_preference_features(entry).items():
            counts = totals.setdefault((feature, value), [0, 0])
            counts[0] += int(entry["rating"])
            counts[1] += 1
    return {key: (value[0], value[1]) for key, value in totals.items()}

def question_preference_score(
    question: Mapping,
    profile: Mapping[tuple[str, str], tuple[int, int]],
) -> float:
    scores = [
        profile[(feature, value)][0] / (profile[(feature, value)][1] + 2)
        for feature, value in question_preference_features(question).items()
        if (feature, value) in profile
    ]
    return sum(scores) / len(scores) if scores else 0.0
