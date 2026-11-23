from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence
from threading import Lock

from .ml import clean_text, classify_with_policy, get_decision_policy, predict_distributions

logger = logging.getLogger(__name__)

_EXAM_QUESTION_PATTERN_CACHE: OrderedDict[str, list[dict]] = OrderedDict()
_EXAM_QUESTION_PATTERN_CACHE_LOCK = Lock()

def _cache_exam_question_patterns(key: str, patterns: list[dict]) -> None:
    with _EXAM_QUESTION_PATTERN_CACHE_LOCK:
        _EXAM_QUESTION_PATTERN_CACHE[key] = patterns
        _EXAM_QUESTION_PATTERN_CACHE.move_to_end(key)
        while len(_EXAM_QUESTION_PATTERN_CACHE) > 4:
            _EXAM_QUESTION_PATTERN_CACHE.popitem(last=False)

def extract_exam_question_patterns(
    exam_sources: Sequence[Mapping],
    training_examples: Sequence[tuple[str, str]],
    training_metrics: dict | None = None,
    dataset_id: str = "builtin",
    decision_policy: Mapping | None = None,
) -> list[dict]:
    import importlib
    compat_questions = importlib.import_module("app.questions")
    policy = dict(decision_policy) if decision_policy is not None else compat_questions.get_decision_policy(
        {"id": dataset_id, "examples": training_examples}
    )
    cache_digest = hashlib.sha256()
    for source in exam_sources:
        cache_digest.update(str(source.get("name", "")).encode("utf-8"))
        cache_digest.update(b"\0")
        cache_digest.update(str(source.get("text", "")).encode("utf-8"))
        cache_digest.update(b"\0")
    for text, topic in training_examples:
        cache_digest.update(text.encode("utf-8"))
        cache_digest.update(b"\0")
        cache_digest.update(topic.encode("utf-8"))
        cache_digest.update(b"\0")
    cache_digest.update(repr(sorted(policy.items())).encode("utf-8"))
    cache_key = cache_digest.hexdigest()
    with _EXAM_QUESTION_PATTERN_CACHE_LOCK:
        cached_patterns = None
        if cache_key in _EXAM_QUESTION_PATTERN_CACHE:
            _EXAM_QUESTION_PATTERN_CACHE.move_to_end(cache_key)
            cached_patterns = _EXAM_QUESTION_PATTERN_CACHE[cache_key]
    if cached_patterns is not None:
        return [dict(item) for item in cached_patterns]

    stems = []
    for source in exam_sources:
        for line in re.split(r"\r?\n+", str(source.get("text", ""))):
            line = re.sub(r"^\s*(?:\d+[.)]|[A-D][.)])\s*", "", line).strip()
            if not 10 <= len(line) <= 300:
                continue
            if not (
                "?" in line
                or re.match(
                    r"^(?:true\s+or\s+false|t/f|what|which|who|when|where|why|how|"
                    r"define|identify|name|state|select|choose)\b",
                    line,
                    re.IGNORECASE,
                )
            ):
                continue
            if re.match(r"^(?:true\s+or\s+false|t/f)\b", line, re.IGNORECASE):
                question_type, pattern = "True or False", "true-false"
            elif re.match(r"^(?:define|identify|name|state)\b", line, re.IGNORECASE):
                question_type = "Identification"
                if re.match(r"^define\b", line, re.IGNORECASE):
                    pattern = "define"
                else:
                    pattern = "identify"
            else:
                question_type = "Multiple Choice"
                if re.match(r"^which\s+of\s+the\s+following\b", line, re.IGNORECASE):
                    pattern = "which-of-following"
                elif re.match(r"^what\b", line, re.IGNORECASE):
                    pattern = "what"
                else:
                    pattern = "which"
            stems.append((line, question_type, pattern))

    stems = [stem for stem in stems if clean_text(stem[0])]
    if not stems:
        _cache_exam_question_patterns(cache_key, [])
        return []
    try:
        distributions = compat_questions.predict_distributions(
            [line for line, _, _ in stems],
            training_examples,
            training_metrics=training_metrics,
        )
    except Exception:
        distributions = []
        classified_stems = []
        for stem in stems:
            try:
                prediction = compat_questions.predict_distributions(
                    [stem[0]],
                    training_examples,
                    training_metrics=training_metrics,
                )
            except Exception as error:
                logger.warning("Skipping exam stem after classifier error: %s", error)
                continue
            if prediction and prediction[0]:
                classified_stems.append(stem)
                distributions.append(prediction[0])
        stems = classified_stems
    frequencies: Counter[tuple[str, str, str]] = Counter()
    for (stem, question_type, pattern), distribution in zip(stems, distributions):
        classified = compat_questions.classify_with_policy(
            stem,
            training_examples,
            dataset_id,
            policy,
            distribution,
        )
        if classified["topic"] == "Unclassified":
            continue
        key = (question_type, classified["topic"], pattern)
        frequencies[key] += 1
    patterns = [
        {
            "question_type": question_type,
            "topic": topic,
            "pattern": pattern,
            "frequency": frequency,
        }
        for (question_type, topic, pattern), frequency in sorted(
            frequencies.items(),
            key=lambda item: (-item[1], item[0]),
        )
    ]
    _cache_exam_question_patterns(cache_key, patterns)
    return [dict(item) for item in patterns]
