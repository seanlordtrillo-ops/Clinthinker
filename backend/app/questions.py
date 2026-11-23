from __future__ import annotations

import hashlib
import itertools
import logging
import math
import random
import re
from threading import Lock
import uuid
from collections import Counter, OrderedDict
from collections.abc import Mapping, Sequence

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .ml import (
    clean_text,
    classify_with_policy,
    get_decision_policy,
    predict_distributions,
)
from .core.checks import checks
from .question_quality import (
    clean_statement,
    definition_record,
    rank_distractors,
    swap_false_statement,
)


from .text_cleaning import _SENTENCE_END, split_sentences, strip_document_headers
from .definitions import (
    _article_for,
    _correct_indefinite_articles,
    _definition,
    _definition_category,
    _definition_headword,
    _is_concept_term,
    _normalize_choice,
    _question_from_definition,
    _question_from_definition_raw,
    _singularize_headword,
    _statement_from_definition,
    _statement_from_definition_raw,
)
from .preferences import (
    question_preference_features,
    question_preference_profile,
    question_preference_score,
)
from .exam_patterns import (
    _cache_exam_question_patterns,
    _EXAM_QUESTION_PATTERN_CACHE,
    _EXAM_QUESTION_PATTERN_CACHE_LOCK,
    extract_exam_question_patterns,
)
from .ranking import (
    _lesson_passages,
    _likelihood_label,
    estimate_difficulty,
    is_duplicate,
    rank_lesson_likelihood,
    topic_priority,
)
from .validation import (
    DEFAULT_PRIORITY_WEIGHTS,
    DIFFICULTIES,
    QUESTION_TYPES,
    validate_candidate,
    validate_weights,
)
from .distractors import _distractor_matches_stem_category, _usable_distractor, _similar_definition_term
from .true_false import _negate_statement

logger = logging.getLogger(__name__)

QUESTION_TYPES = {"Multiple Choice", "True or False", "Identification"}
DIFFICULTIES = {"Easy", "Moderate", "Difficult"}
DEFAULT_SIMILARITY_THRESHOLD = 0.82


































































@checks(
    expected="Generated question result",
    probable_cause="Question generation failed",
)
def generate_questions(
    *,
    requested_count: int,
    question_type: str,
    difficulty: str,
    topic_filter: str,
    per_topic: int,
    training_examples: Sequence[tuple[str, str]],
    dataset_id: str,
    dataset_name: str,
    sources: Sequence[Mapping],
    lesson_mode: bool = False,
    training_metrics: dict | None = None,
    saved_question_texts: Sequence[str] = (),
    preference_feedback: Sequence[Mapping] = (),
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    allow_repeats: bool = False,
    used_excerpts: Sequence[str | Mapping] = (),
    used_question_forms: Sequence[tuple[str, ...]] = (),
    random_seed: int | None = None,
    priority_weights: Mapping[str, float] | None = None,
    decision_policy: Mapping | None = None,
) -> dict:
    policy = dict(decision_policy) if decision_policy is not None else get_decision_policy(
        {"id": dataset_id, "examples": training_examples}
    )
    if question_type not in QUESTION_TYPES:
        raise ValueError("Choose a supported question type.")
    if difficulty not in DIFFICULTIES:
        raise ValueError("Choose Easy, Moderate, or Difficult difficulty.")
    if not 1 <= requested_count <= 50 or not 1 <= per_topic <= 50:
        raise ValueError("Question count and per-topic limit must be between 1 and 50.")
    if not 0.5 <= similarity_threshold <= 1:
        raise ValueError("Similarity threshold must be between 0.5 and 1.0.")
    weights = validate_weights(priority_weights)
    if not training_examples:
        raise ValueError("The selected training dataset is empty.")
    topics = sorted({label.strip() for _, label in training_examples if label.strip()})
    if len(topics) < 2:
        raise ValueError("The selected training dataset needs at least two topics.")
    material_sources = [
        source for source in sources
        if source.get("kind") in {"course", "lesson"}
    ]
    if not material_sources:
        raise ValueError("Select at least one saved course material source.")

    cleaned_sources = []
    removed_header_lines = 0
    for source in sources:
        source_text, removed = strip_document_headers(str(source.get("text", "")))
        removed_header_lines += removed
        if source_text.strip():
            cleaned_sources.append({**source, "text": source_text})
    sources = cleaned_sources
    source_texts = [str(source.get("text", "")) for source in sources if source.get("text")]
    if not source_texts:
        raise ValueError("No readable course materials or training examples were found.")
    combined_source = "\n".join(source_texts)
    if len(combined_source) > 500_000:
        raise ValueError("Selected source text exceeds the 500,000 character analysis limit.")

    all_definition_records = []
    lesson_definition_records = []
    if lesson_mode:
        for source in sources:
            source_kind = str(source.get("kind", "course"))
            if source_kind not in {"course", "lesson"}:
                continue
            source_id = str(source.get("id") or source.get("name") or "")
            for raw_sentence in _SENTENCE_END.split(str(source.get("text", ""))):
                sentence = raw_sentence.strip(" \t-•")
                if not _definition(sentence):
                    continue
                record = definition_record(
                    sentence,
                    source_id=source_id,
                    source_kind=source_kind,
                )
                if record:
                    all_definition_records.append(record)
                    lesson_definition_records.append(record)

    candidate_sources = []
    diagnostics: Counter[str] = Counter()
    raw_sentence_count = 0
    for source in sources:
        raw_sentences = _SENTENCE_END.split(str(source.get("text", "")))
        raw_sentence_count += len(raw_sentences)
        for source_order, raw_sentence in enumerate(raw_sentences):
            sentence = raw_sentence.strip(" \t-•")
            if not 24 <= len(sentence) <= 500:
                diagnostics["outside_sentence_length"] += 1
                continue
            if sentence.endswith("?"):
                diagnostics["already_a_question"] += 1
                continue
            if not clean_text(sentence):
                diagnostics["no_readable_words"] += 1
                continue
            definition = _definition(sentence)
            if question_type == "True or False" and definition is None:
                diagnostics["not_definition"] += 1
                continue
            eligible = estimate_difficulty(sentence) == difficulty or (
                lesson_mode
                and definition is not None
            )
            if not eligible:
                diagnostics["different_difficulty"] += 1
                if question_type not in {"Multiple Choice", "Identification"} or not definition:
                    continue
            if question_type in {"Multiple Choice", "Identification"} and not definition:
                if eligible:
                    diagnostics["not_definition"] += 1
                continue
            candidate_sources.append((source, sentence, definition, eligible, source_order))

    distributions = predict_distributions(
        [combined_source, *(sentence for _, sentence, _, _, _ in candidate_sources)],
        training_examples,
        training_metrics=training_metrics,
    )
    aggregate = distributions[0]
    confidences = {entry["topic"]: entry["confidence"] for entry in aggregate}
    priority_topics = [*topics, "Unclassified"] if lesson_mode else topics
    ranked_topics = topic_priority(
        priority_topics, training_examples, [str(s["text"]) for s in material_sources],
        confidences, weights
    )
    priorities = {entry["topic"]: entry for entry in ranked_topics}
    if topic_filter != "All Topics" and topic_filter not in priorities:
        raise ValueError("The selected topic is not part of this training dataset.")
    allowed_topics = (
        [topic_filter] if topic_filter != "All Topics" else [item["topic"] for item in ranked_topics]
    )

    classified = []
    definitions_by_source: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for candidate, distribution in zip(candidate_sources, distributions[1:]):
        source, sentence, definition, eligible, source_order = candidate
        classification = classify_with_policy(
            sentence,
            training_examples,
            dataset_id,
            policy,
            distribution,
        )
        best = {**distribution[0], **classification}
        if not lesson_mode and best["topic"] == "Unclassified":
            best["topic"] = distribution[0]["topic"]
        source_key = (
            str(source.get("kind", "course")),
            str(source.get("id") or source.get("name") or ""),
        )
        if definition:
            record = definition_record(
                sentence,
                source_id=source_key[1],
                source_kind=source_key[0],
                topic=best["topic"],
            )
            if record:
                all_definition_records.append(record)
                if source_key[0] in {"course", "lesson"}:
                    lesson_definition_records.append(record)
        if lesson_mode and best["topic"] == "Unclassified":
            diagnostics["low_confidence_unclassified"] += 1
        classified.append((source, sentence, definition, eligible, best, source_order))
        if definition and best["abstain_reason"] is None:
            definitions_by_source.setdefault(
                (best["topic"], *source_key), []
            ).append(definition)

    training_definitions_by_topic: dict[str, list[tuple[str, str]]] = {}
    for text, topic in training_examples:
        for sentence in _SENTENCE_END.split(text):
            definition = _definition(sentence)
            if definition:
                training_definitions_by_topic.setdefault(topic.strip(), []).append(
                    definition
                )
    candidates: list[dict] = []
    candidate_distractor_pools: dict[str, list[tuple[str, str]]] = {}
    request_random = random.Random(random_seed if random_seed is not None else 0)
    eligible_sentence_count = sum(candidate[3] for candidate in candidate_sources)
    for source, sentence, definition, eligible, best, source_order in classified:
        if not eligible:
            continue
        if best["topic"] not in allowed_topics:
            diagnostics["topic_not_selected"] += 1
            continue
        if best["abstain_reason"] is not None:
            if not lesson_mode:
                diagnostics["below_topic_relevance"] += 1
                continue

        candidate_question_type = question_type
        fallback_to_true_false = False
        false_statement = None
        false_basis = None
        source_defined_terms: list[str] = []
        distractors: list[tuple[str, str]] = []
        if question_type == "True or False":
            if not definition:
                diagnostics["no_safe_negation"] += 1
                continue
            term, explanation = definition
            supported_statement = _statement_from_definition(term, explanation)
            supported_statement = clean_statement(supported_statement)
            if not supported_statement:
                diagnostics["unclean_sentence"] += 1
                continue
            source_definition = definition_record(
                sentence,
                source_id=str(source.get("id") or source.get("name") or ""),
                source_kind=str(source.get("kind", "course")),
                topic=best["topic"],
            )
            swapped = (
                swap_false_statement(source_definition, all_definition_records)
                if source_definition
                else None
            )
            if swapped:
                false_statement, false_basis = swapped
            else:
                false_statement = clean_statement(
                    _negate_statement(supported_statement) or ""
                )
                if not false_statement:
                    diagnostics["no_safe_negation"] += 1
            question = supported_statement
            answer = "True"
            choices: list[str] = []
            excerpt = explanation
        else:
            term, explanation = definition
            if not _is_concept_term(term):
                diagnostics["not_definition"] += 1
                continue
            question = _question_from_definition(term, explanation, source_order)
            if not question:
                diagnostics["no_natural_stem"] += 1
                continue
            if question_type == "Identification":
                answer = term
                choices = []
            else:
                current_source_key = (
                    str(source.get("kind", "course")),
                    str(source.get("id") or source.get("name") or ""),
                )
                same_source_topic = [
                    record for record in lesson_definition_records
                    if record["source_id"] == current_source_key[1]
                    and (
                        best["topic"] == "Unclassified"
                        or record["topic"] == best["topic"]
                    )
                ]
                same_lesson = [
                    record for record in lesson_definition_records
                    if record["source_id"] == current_source_key[1]
                ]
                any_lesson = list(lesson_definition_records)
                same_source = definitions_by_source.get(
                    (best["topic"], *current_source_key), []
                )
                other_material_sources = [
                    record
                    for (topic, kind, source_id), terms in definitions_by_source.items()
                    if topic == best["topic"]
                    and kind in {"course", "lesson"}
                    and (kind, source_id) != current_source_key
                    for record in (
                        {"term": distractor, "explanation": distractor_explanation}
                        for distractor, distractor_explanation in terms
                    )
                ]
                tiers = (
                    [same_source_topic, same_lesson, any_lesson]
                    if lesson_mode
                    else [
                        [
                            {
                                "term": distractor,
                                "explanation": distractor_explanation,
                            }
                            for distractor, distractor_explanation in same_source
                        ],
                        other_material_sources,
                        [
                            {"term": distractor, "explanation": distractor_explanation}
                            for distractor, distractor_explanation in (
                                training_definitions_by_topic.get(best["topic"], [])
                            )
                        ],
                    ]
                )
                source_defined_terms = [
                    str(record["term"])
                    for tier in tiers
                    for record in tier
                ]
                seen_terms = {re.sub(r"\s+", " ", term).strip().casefold()}
                for tier in tiers:
                    ranked_tier = rank_distractors(term, tier)
                    for record in ranked_tier:
                        distractor = str(record["term"])
                        distractor_explanation = str(record["explanation"])
                        example_stem = re.search(
                            r"\ban example of\b", question, re.IGNORECASE
                        )
                        hardware_stem = (
                            "hardware" in term.casefold()
                            and _distractor_matches_stem_category(
                                "Which term describes hardware?",
                                distractor_explanation,
                                distractor,
                            )
                        )
                        if (
                            example_stem
                            and _distractor_matches_stem_category(
                                question, distractor_explanation, distractor
                            )
                        ) or hardware_stem:
                            continue
                        if re.search(
                            rf"\bexamples?\s+of\s+(?:an?\s+|the\s+)?{re.escape(term)}\b",
                            distractor_explanation,
                            re.IGNORECASE,
                        ):
                            continue
                        distractor = _normalize_choice(distractor)
                        folded = re.sub(r"\s+", " ", distractor).strip().casefold()
                        if folded in seen_terms or not _usable_distractor(
                            distractor,
                            term,
                            question,
                            sentence,
                            set(),
                            source_defined_terms,
                        ):
                            continue
                        if (
                            best["topic"] != "Unclassified"
                            and not _similar_definition_term(term, distractor)
                        ):
                            continue
                        seen_terms.add(folded)
                        distractors.append((distractor, distractor_explanation))
                if len(distractors) < 3:
                    supported_statement = clean_statement(
                        _statement_from_definition(term, explanation)
                    )
                    source_definition = definition_record(
                        sentence,
                        source_id=current_source_key[1],
                        source_kind=current_source_key[0],
                        topic=best["topic"],
                    )
                    swapped = (
                        swap_false_statement(source_definition, all_definition_records)
                        if source_definition
                        else None
                    )
                    if not supported_statement:
                        diagnostics["unclean_sentence"] += 1
                        continue
                    if swapped:
                        false_statement, false_basis = swapped
                    else:
                        false_statement = clean_statement(
                            _negate_statement(supported_statement) or ""
                        )
                    if not false_statement:
                        diagnostics["no_safe_negation"] += 1
                        continue
                    candidate_question_type = "True or False"
                    fallback_to_true_false = True
                    question = supported_statement
                    answer = "True"
                    choices = []
                    excerpt = explanation
                else:
                    wrong = [item[0] for item in distractors[:3]]
                    answer = _normalize_choice(term)
                    choices = [answer, *wrong]
                    seed = int(hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:8], 16)
                    random.Random(seed ^ uuid.uuid4().int).shuffle(choices)
            if candidate_question_type != "True or False":
                excerpt = explanation

        source_label = str(source.get("name", "Selected source"))
        reference_text = sentence
        source_metadata = (
            f"Source Dataset: {dataset_name}\n"
            f"Source Material: {source_label}\n"
            f"Source Topic: {best['topic']}\n"
            f"Source Text/Reference: {reference_text}"
        )
        candidate_id = str(uuid.uuid4())
        if candidate_question_type == "Multiple Choice":
            candidate_distractor_pools[candidate_id] = distractors
        candidate = {
            "id": candidate_id,
            "question_text": question,
            "question_type": candidate_question_type,
            "topic": best["topic"],
            "difficulty": difficulty,
            "choices": choices,
            "correct_answer": answer,
            "priority_score": priorities[best["topic"]]["priority_score"],
            "confidence_score": round(float(best["confidence"]), 4),
            "source_dataset_id": dataset_id,
            "source_dataset_name": dataset_name,
            "source_material_id": source.get("id"),
            "source_material_name": source_label,
            "source_reference": source_metadata,
            "cited_passage": sentence,
            "support_excerpt": excerpt,
            "source_content": str(source.get("text", "")),
            "lesson_order": source_order,
            "_alternate_form": candidate_question_type != question_type,
            "_fallback_form": fallback_to_true_false,
            "created_at": None,
        }
        if candidate_question_type == "True or False":
            candidate["supported_statement"] = supported_statement
            candidate["false_statement"] = false_statement
            candidate["false_basis"] = false_basis
            if false_basis:
                candidate["source_content"] = combined_source
        if candidate_question_type == "Multiple Choice":
            candidate["source_defined_terms"] = source_defined_terms
        if not validate_candidate(
            candidate,
            candidate_question_type,
        ):
            if candidate_question_type == "True or False" and lesson_mode:
                diagnostics["no_valid_distractors"] += 1
            diagnostics["candidate_validation_failed"] += 1
            continue
        candidates.append(candidate)

    base_candidates = list(candidates)
    all_defined_terms = [str(record["term"]) for record in all_definition_records]
    for candidate in base_candidates:
        definition = _definition(candidate["cited_passage"])
        if not definition:
            continue
        term, explanation = definition
        if candidate["question_type"] == "Multiple Choice":
            supported_statement = clean_statement(
                _statement_from_definition(term, explanation)
            )
            if not supported_statement:
                continue
            source_definition = definition_record(
                candidate["cited_passage"],
                source_id=str(candidate.get("source_material_id") or ""),
                source_kind="lesson" if lesson_mode else "course",
                topic=candidate["topic"],
            )
            swapped = (
                swap_false_statement(source_definition, all_definition_records)
                if source_definition
                else None
            )
            false_statement, false_basis = swapped or (
                clean_statement(_negate_statement(supported_statement) or ""),
                None,
            )
            alternate = {
                **candidate,
                "id": f"{candidate['id']}:true-false",
                "_alternate_form": True,
                "question_text": supported_statement,
                "question_type": "True or False",
                "choices": [],
                "correct_answer": "True",
                "supported_statement": supported_statement,
                "false_statement": false_statement,
                "false_basis": false_basis,
            }
            if false_basis:
                alternate["source_content"] = combined_source
            if validate_candidate(alternate, "True or False"):
                candidates.append(alternate)
        elif candidate["question_type"] == "True or False":
            if not _is_concept_term(term):
                continue
            question = _question_from_definition(
                term, explanation, int(candidate.get("lesson_order", 0))
            )
            if not question:
                continue
            distractors = []
            seen_terms = {re.sub(r"\s+", " ", term).strip().casefold()}
            for record in rank_distractors(term, all_definition_records):
                distractor = _normalize_choice(str(record["term"]))
                folded = re.sub(r"\s+", " ", distractor).strip().casefold()
                if (
                    folded in seen_terms
                    or (
                        candidate["topic"] != "Unclassified"
                        and not _similar_definition_term(term, distractor)
                    )
                    or not _usable_distractor(
                        distractor,
                        term,
                        question,
                        candidate["cited_passage"],
                        set(),
                        all_defined_terms,
                    )
                ):
                    continue
                seen_terms.add(folded)
                distractors.append((distractor, str(record["explanation"])))
            if len(distractors) == 3:
                alternate = {
                    **candidate,
                    "id": f"{candidate['id']}:multiple-choice",
                    "_alternate_form": True,
                    "question_text": question,
                    "question_type": "Multiple Choice",
                    "choices": [],
                    "correct_answer": _normalize_choice(term),
                    "supported_statement": None,
                    "false_statement": None,
                    "false_basis": None,
                    "source_defined_terms": all_defined_terms,
                }
                candidate_distractor_pools[alternate["id"]] = distractors
                if validate_candidate(alternate, "Multiple Choice"):
                    candidates.append(alternate)
        elif candidate["question_type"] == "Identification":
            alternate = {
                **candidate,
                "id": f"{candidate['id']}:reverse-identification",
                "_alternate_form": True,
                "question_text": f"What does {term} mean?",
                "correct_answer": explanation,
                "question_direction": "term_to_definition",
            }
            if validate_candidate(alternate, "Identification"):
                candidates.append(alternate)

    if preference_feedback:
        preference_profile = question_preference_profile(preference_feedback)
        candidates.sort(
            key=lambda item: (
                item.get("_alternate_form", False),
                -question_preference_score(item, preference_profile),
                -priorities[item["topic"]]["priority_score"],
                (
                    request_random.random()
                    if random_seed is not None
                    else item["source_material_name"].casefold()
                ),
            )
        )
    else:
        candidates.sort(
            key=lambda item: (
                item.get("_alternate_form", False),
                -priorities[item["topic"]]["priority_score"],
                (
                    request_random.random()
                    if random_seed is not None
                    else item["source_material_name"].casefold()
                ),
            )
        )
    if lesson_mode and len(material_sources) > 1:
        by_source: dict[str, list[dict]] = {
            str(source.get("id") or source.get("name") or ""): []
            for source in material_sources
        }
        for candidate in candidates:
            by_source.setdefault(str(candidate.get("source_material_id") or ""), []).append(
                candidate
            )
        fair_share = math.ceil(requested_count / len(material_sources))
        balanced = []
        for offset in range(fair_share):
            for source in material_sources:
                rows = by_source.get(str(source.get("id") or source.get("name") or ""), [])
                if offset < len(rows):
                    balanced.append(rows[offset])
        balanced_ids = {id(candidate) for candidate in balanced}
        candidates = balanced + [
            candidate for candidate in candidates if id(candidate) not in balanced_ids
        ]
    def normalize_excerpt(excerpt: object) -> str:
        return re.sub(r"\s+", " ", str(excerpt)).strip().casefold()

    history_by_excerpt: dict[str, list[dict]] = {}
    for history_item in used_excerpts:
        if isinstance(history_item, Mapping):
            record = dict(history_item)
        else:
            record = {"support_excerpt": str(history_item)}
        excerpt_key = normalize_excerpt(record.get("support_excerpt", ""))
        if excerpt_key:
            record["support_excerpt"] = excerpt_key
            record["use_count"] = max(1, int(record.get("use_count", 1)))
            record["last_used_at"] = str(record.get("last_used_at", ""))
            history_by_excerpt.setdefault(excerpt_key, []).append(record)
    for form in used_question_forms:
        if len(form) >= 2:
            excerpt, form_type = form[:2]
            direction = form[2] if len(form) >= 3 else (
                "statement" if form_type == "True or False" else "definition_to_term"
            )
            excerpt_key = normalize_excerpt(excerpt)
            if not any(
                str(record.get("question_type", "")).casefold() == str(form_type).casefold()
                and str(record.get("question_direction") or (
                    "statement"
                    if record.get("question_type") == "True or False"
                    else "definition_to_term"
                )).casefold() == str(direction).casefold()
                for record in history_by_excerpt.get(excerpt_key, [])
            ):
                history_by_excerpt.setdefault(excerpt_key, []).append({
                    "support_excerpt": excerpt_key,
                    "question_type": str(form_type),
                    "question_direction": str(direction),
                    "use_count": 1,
                    "last_used_at": "",
                })

    def candidate_direction(item: Mapping) -> str:
        return str(item.get("question_direction") or (
            "statement"
            if item["question_type"] == "True or False"
            else "definition_to_term"
        )).casefold()

    def record_signature(record: Mapping) -> tuple:
        choices = record.get("choices", ())
        if isinstance(choices, str):
            choices = ()
        return (
            str(record.get("question_text", "")).strip().casefold(),
            str(record.get("question_type", "")).casefold(),
            str(record.get("question_direction") or (
                "statement"
                if record.get("question_type") == "True or False"
                else "definition_to_term"
            )).casefold(),
            tuple(sorted(str(choice).strip().casefold() for choice in choices)),
            str(record.get("correct_answer", "")).strip().casefold(),
        )

    def candidate_signature(item: Mapping) -> tuple:
        return record_signature(item)

    history_signatures: dict[str, set[tuple]] = {}
    history_option_sets: dict[str, set[frozenset[str]]] = {}
    history_type_directions: dict[str, set[tuple[str, str]]] = {}
    history_false_statements: dict[str, list[str]] = {}
    for excerpt_key, records in history_by_excerpt.items():
        history_signatures[excerpt_key] = set()
        history_option_sets[excerpt_key] = set()
        history_type_directions[excerpt_key] = set()
        for record in records:
            if record.get("question_text"):
                history_signatures[excerpt_key].add(record_signature(record))
            if record.get("question_type"):
                history_type_directions[excerpt_key].add(
                    (
                        str(record["question_type"]).casefold(),
                        str(record.get("question_direction") or (
                            "statement"
                            if record["question_type"] == "True or False"
                            else "definition_to_term"
                        )).casefold(),
                    )
                )
            choices = record.get("choices", ())
            if choices and not isinstance(choices, str):
                history_option_sets[excerpt_key].add(
                    frozenset(str(choice).strip().casefold() for choice in choices)
                )
            if (
                str(record.get("question_type", "")).casefold() == "true or false"
                and str(record.get("correct_answer", "")).casefold() == "false"
                and record.get("question_text")
            ):
                history_false_statements.setdefault(excerpt_key, []).append(
                    str(record["question_text"])
                )

    usage_counts = {
        excerpt: sum(record["use_count"] for record in records)
        for excerpt, records in history_by_excerpt.items()
    }
    last_used_at = {
        excerpt: max(
            (record["last_used_at"].replace(" ", "T") for record in records),
            default="",
        )
        for excerpt, records in history_by_excerpt.items()
    }
    fresh_candidates = []
    used_candidates = []
    for item in candidates:
        excerpt_key = normalize_excerpt(item["support_excerpt"])
        if excerpt_key not in history_by_excerpt:
            fresh_candidates.append(item)
            continue
        form_is_used = (
            str(item["question_type"]).casefold(),
            candidate_direction(item),
        ) in history_type_directions.get(excerpt_key, set())
        used_candidates.append((
            usage_counts.get(excerpt_key, 0),
            last_used_at.get(excerpt_key, ""),
            form_is_used,
            item,
        ))
    candidates = fresh_candidates + [
        item for _, _, _, item in sorted(
            used_candidates,
            key=lambda row: (row[0], row[1], row[2]),
        )
    ]
    if question_type == "Multiple Choice" and not history_by_excerpt:
        candidates = [
            item for item in candidates
            if not item.get("_alternate_form", False)
            or (
                item.get("_fallback_form", False)
                and item["question_type"] == "True or False"
            )
        ]
        candidates = [
            item for item in candidates if item["question_type"] == "Multiple Choice"
        ] + [
            item for item in candidates if item["question_type"] != "Multiple Choice"
        ]
    true_false_offset = (
        int(hashlib.sha256(combined_source.encode("utf-8")).hexdigest()[:1], 16) % 2
    )
    counts: Counter[str] = Counter()
    accepted = []
    previous = ([] if allow_repeats else list(saved_question_texts)) + [
        text for text, _ in training_examples
        if text.strip().endswith("?")
        or re.match(
            r"^\s*(?:what|which|who|when|where|why|how|define|explain|describe|"
            r"compare|list|state|identify|discuss)\b",
            text,
            re.IGNORECASE,
        )
    ]
    accepted_option_sets: set[frozenset[str]] = set()
    used_distractors: set[str] = set()
    accepted_excerpt_keys: set[str] = set()
    accepted_signatures: set[tuple] = set()
    accepted_stems: set[str] = set()
    for candidate in candidates:
        if len(accepted) >= requested_count:
            break
        # "Unclassified" is not a real topic, so in lesson mode it is not limited by the per-topic cap.
        if counts[candidate["topic"]] >= per_topic and not (
            lesson_mode and candidate["topic"] == "Unclassified"
        ):
            diagnostics["per_topic_limit_reached"] += 1
            continue
        excerpt_key = normalize_excerpt(candidate["support_excerpt"])
        if excerpt_key in accepted_excerpt_keys:
            continue
        is_reused_excerpt = excerpt_key in history_by_excerpt
        other_answers = {
            str(item["correct_answer"]).casefold()
            for item in accepted
            if item["question_type"] == "Multiple Choice"
        }
        selected_option_set = None
        if candidate["question_type"] == "Multiple Choice":
            eligible_options = [
                distractor
                for distractor, _ in candidate_distractor_pools.get(candidate["id"], [])
                if _usable_distractor(
                    distractor,
                    candidate["correct_answer"],
                    candidate["question_text"],
                    candidate["cited_passage"],
                    other_answers,
                    candidate.get("source_defined_terms", ()),
                )
                and (
                    candidate.get("topic") == "Unclassified"
                    or _similar_definition_term(candidate["correct_answer"], distractor)
                )
            ]
            options = [
                distractor for distractor in eligible_options
                if (
                    is_reused_excerpt
                    or candidate.get("topic") == "Unclassified"
                    or distractor.casefold() not in used_distractors
                )
            ]
            selected_choices = None
            option_pools = [options]
            if (
                not is_reused_excerpt
                and candidate.get("topic") != "Unclassified"
                and len({
                    term.casefold()
                    for term in candidate.get("source_defined_terms", all_defined_terms)
                }) <= 6
            ):
                option_pools.append(eligible_options)
            for option_pool in option_pools:
                for distractor_set in itertools.combinations(option_pool, 3):
                    choices = [candidate["correct_answer"], *distractor_set]
                    option_set = frozenset(choice.casefold() for choice in choices)
                    if (
                        option_set in accepted_option_sets
                        or (
                            is_reused_excerpt
                            and option_set in history_option_sets.get(excerpt_key, set())
                        )
                    ):
                        continue
                    selected_choices = choices
                    selected_option_set = option_set
                    break
                if selected_choices is not None:
                    break
            if selected_choices is None:
                diagnostics["not_enough_distinct_distractors"] += 1
                continue
            else:
                random.Random(
                    int(hashlib.sha256(candidate["cited_passage"].encode("utf-8")).hexdigest()[:8], 16)
                    ^ uuid.uuid4().int
                ).shuffle(selected_choices)
                candidate = {**candidate, "choices": selected_choices}
        if not validate_candidate(
            candidate,
            candidate["question_type"],
            other_correct_answers=[
                *(
                    item["correct_answer"]
                    for item in accepted
                    if item["question_type"] == "Multiple Choice"
                ),
            ],
        ):
            diagnostics["candidate_validation_failed"] += 1
            continue
        if candidate["question_type"] == "True or False":
            supported_statement = candidate["supported_statement"]
            negated_statement = candidate.get("false_statement") or clean_statement(
                _negate_statement(supported_statement) or ""
            )
            prior_false_statements = history_false_statements.get(excerpt_key, [])
            if (
                is_reused_excerpt
                and negated_statement
                and normalize_excerpt(negated_statement) in {
                    normalize_excerpt(statement) for statement in prior_false_statements
                }
            ):
                source_definition = definition_record(candidate["cited_passage"])
                swapped = (
                    swap_false_statement(
                        source_definition,
                        all_definition_records,
                        excluded_statements=prior_false_statements,
                    )
                    if source_definition
                    else None
                )
                if swapped:
                    negated_statement, false_basis = swapped
                    candidate["false_statement"] = negated_statement
                    candidate["false_basis"] = false_basis
                    candidate["source_content"] = combined_source
            answer = (
                "True"
                if negated_statement is None or (len(accepted) + true_false_offset) % 2 == 0
                else "False"
            )
            answer_order = [answer, "False" if answer == "True" else "True"]
            selected_tf_candidate = None
            for candidate_answer in answer_order:
                statement = (
                    supported_statement
                    if candidate_answer == "True"
                    else negated_statement
                )
                if not statement:
                    continue
                proposed = {
                    **candidate,
                    "question_text": statement,
                    "correct_answer": candidate_answer,
                }
                signature = candidate_signature(proposed)
                if (
                    signature in history_signatures.get(excerpt_key, set())
                    or signature in accepted_signatures
                    or normalize_excerpt(statement) in accepted_stems
                ):
                    continue
                if validate_candidate(proposed, candidate["question_type"]):
                    selected_tf_candidate = proposed
                    break
            if not selected_tf_candidate:
                diagnostics["candidate_validation_failed"] += 1
                continue
            candidate = selected_tf_candidate
        signature = candidate_signature(candidate)
        if (
            signature in history_signatures.get(excerpt_key, set())
            or signature in accepted_signatures
            or normalize_excerpt(candidate["question_text"]) in accepted_stems
        ):
            diagnostics["used_excerpt_form"] += 1
            continue
        if is_duplicate(candidate["question_text"], previous, similarity_threshold):
            diagnostics["too_similar"] += 1
            continue
        candidate.pop("_alternate_form", None)
        candidate.pop("_fallback_form", None)
        accepted.append(candidate)
        accepted_excerpt_keys.add(excerpt_key)
        accepted_signatures.add(signature)
        accepted_stems.add(normalize_excerpt(candidate["question_text"]))
        if selected_option_set is not None:
            accepted_option_sets.add(selected_option_set)
            used_distractors.update(
                choice.casefold()
                for choice in candidate["choices"]
                if choice.casefold() != candidate["correct_answer"].casefold()
            )
        counts[candidate["topic"]] += 1
        previous.append(candidate["question_text"])
    too_similar_count = diagnostics["too_similar"]
    other_rejection_count = max(
        (
            count for reason, count in diagnostics.items()
            if reason != "too_similar"
        ),
        default=0,
    )
    too_similar_is_primary = (
        too_similar_count > 0 and too_similar_count >= other_rejection_count
    )
    return {
        "questions": accepted,
        "diagnostics": {
            "source_sentence_count": raw_sentence_count,
            "header_lines_skipped": removed_header_lines,
            "sentences_matching_filters": eligible_sentence_count,
            **(
                {
                    "low_confidence_unclassified": diagnostics["low_confidence_unclassified"],
                    "skipped_low_confidence": diagnostics["below_topic_relevance"],
                    "no_valid_distractors": (
                        diagnostics["no_valid_distractors"]
                        + diagnostics["not_enough_distinct_distractors"]
                    ),
                }
                if lesson_mode else {}
            ),
            "rejections": [
                {"reason": reason, "count": count}
                for reason, count in sorted(diagnostics.items())
                if count and reason != "low_confidence_unclassified"
            ],
        },
        "topic_priorities": ranked_topics,
        "priority_weights": weights,
        "minimum_topic_confidence": float(policy["confidence_threshold"]),
        "requested_count": requested_count,
        "shortfall": max(0, requested_count - len(accepted)),
        "shortfall_reason": (
            "Most candidate questions were too similar to previously saved questions. "
            "Raise the duplicate similarity threshold to allow closer matches, add lesson "
            "files for more source variety, or clear old saved questions."
            if too_similar_is_primary
            else "The per-topic question cap limited the result. Raise the questions-per-topic "
            "limit or select more topics."
            if (
                len(accepted) < requested_count
                and diagnostics["per_topic_limit_reached"] > 0
                and diagnostics["per_topic_limit_reached"] >= max(
                    diagnostics["not_enough_distinct_distractors"],
                    diagnostics["below_topic_relevance"],
                )
            )
            else "Not enough questions had three valid source-defined distractors. Try a different "
            "question type or add lessons with more defined terms."
            if (
                len(accepted) < requested_count
                and diagnostics["not_enough_distinct_distractors"] > 0
                and diagnostics["not_enough_distinct_distractors"] >= diagnostics["below_topic_relevance"]
            )
            else (
                "The selected training data did not match source sentences with at least "
                f"{float(policy['confidence_threshold']):.0%} model relevance. Choose a better-matched "
                "dataset or source material."
                if (
                    not candidates
                    and eligible_sentence_count > 0
                    and diagnostics["below_topic_relevance"] >= eligible_sentence_count
                )
                else "Not enough distinct, source-supported questions passed the quality checks."
            )
            if len(accepted) < requested_count
            else None
        ),
        "disclaimer": (
            "Priority indicates topic relevance in the selected sources; it is not a "
            "prediction or guarantee that a topic will appear on an examination."
        ),
    }
