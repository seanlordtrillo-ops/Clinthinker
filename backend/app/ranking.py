from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .ml import clean_text, classify_with_policy, get_decision_policy, predict_distributions
from .text_cleaning import _SENTENCE_END
from .definitions import _definition
from .validation import validate_weights

_COMPLEXITY_CUES = {
    "analyze", "compare", "contrast", "differentiate", "evaluate",
    "implications", "relationship", "whereas",
}

def _lesson_passages(text: str) -> list[dict]:
    passages = []
    current = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                passages.append("\n".join(current))
                current = []
            continue
        current.append(stripped)
    if current:
        passages.append("\n".join(current))
    if not passages:
        passages = [text.strip()]

    result = []
    for passage in passages:
        for sentence in _SENTENCE_END.split(passage):
            list_item = bool(re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", sentence))
            sentence = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", sentence).strip()
            heading = (
                len(sentence) <= 100
                and not sentence.endswith((".", "?", "!"))
            )
            if (len(sentence) < 24 and not heading and not list_item) or not clean_text(sentence):
                continue
            result.append(
                {
                    "text": sentence,
                    "heading": heading,
                    "definition": _definition(sentence) is not None,
                    "list_item": list_item,
                }
            )
    return result

def rank_lesson_likelihood(
    questions: list[dict],
    lesson_text: str,
    training_examples: Sequence[tuple[str, str]],
    *,
    exam_sources: Sequence[Mapping] = (),
    recent_question_topics: Sequence[str] = (),
    emphasized_terms: Sequence[str] = (),
    heading_terms: Sequence[str] = (),
    list_terms: Sequence[str] = (),
    training_metrics: dict | None = None,
    dataset_id: str = "builtin",
    decision_policy: Mapping | None = None,
) -> dict:
    import importlib
    compat_questions = importlib.import_module("app.questions")
    policy = dict(decision_policy) if decision_policy is not None else compat_questions.get_decision_policy(
        {"id": dataset_id, "examples": training_examples}
    )
    topics = sorted({label.strip() for _, label in training_examples if label.strip()})
    passages = _lesson_passages(lesson_text)
    distributions = compat_questions.predict_distributions(
        [passage["text"] for passage in passages],
        training_examples,
        training_metrics=training_metrics,
    ) if passages else []
    frequencies = Counter(
        token.casefold()
        for passage in passages
        for token in clean_text(passage["text"]).split()
    )
    tfidf_weights = dict.fromkeys(range(len(passages)), 0.0)
    if passages:
        passage_matrix = TfidfVectorizer().fit_transform(
            [passage["text"] for passage in passages]
        )
        for index, row in enumerate(passage_matrix):
            weights = row.data
            tfidf_weights[index] = (
                sum(sorted(weights, reverse=True)[:5]) / 5
                if len(weights) else 0.0
            )
    maximum_tfidf = max(tfidf_weights.values(), default=0.0) or 1.0
    maximum_frequency = max(frequencies.values(), default=1)
    emphasized = Counter(
        token.casefold()
        for term in emphasized_terms
        for token in clean_text(term).split()
    )
    heading_phrases = [clean_text(term) for term in heading_terms if clean_text(term)]
    list_phrases = [clean_text(term) for term in list_terms if clean_text(term)]
    emphasis_scores = dict.fromkeys(topics, 0.0)
    topic_passage_counts = Counter()
    emphasis_signal_counts: dict[str, Counter] = {
        topic: Counter() for topic in topics
    }
    analyzed_passages = []
    for passage_index, (passage, distribution) in enumerate(zip(passages, distributions)):
        classification = compat_questions.classify_with_policy(
            passage["text"],
            training_examples,
            dataset_id,
            policy,
            distribution,
        )
        topic = classification["topic"]
        cleaned_passage = clean_text(passage["text"])
        passage_tokens = set(cleaned_passage.split())
        emphasized_in_passage = sorted(passage_tokens & set(emphasized))
        repeated_in_passage = sorted(
            token for token in passage_tokens if frequencies[token] >= 3
        )
        is_heading = passage["heading"] or any(
            phrase in cleaned_passage for phrase in heading_phrases
        )
        is_list = passage["list_item"] or any(
            phrase in cleaned_passage for phrase in list_phrases
        )
        analyzed_passages.append(
            {
                "text": passage["text"],
                "topic": topic,
                "confidence": round(float(classification["confidence"]), 3),
                "margin": round(float(classification["margin"]), 3),
                "models_agree": classification["models_agree"],
                "abstain_reason": classification["abstain_reason"],
                "signals": {
                    "heading": is_heading,
                    "definition": passage["definition"],
                    "list": is_list,
                    "emphasized_terms": emphasized_in_passage,
                    "repeated_terms": repeated_in_passage,
                },
            }
        )
        if topic == "Unclassified":
            continue
        topic_passage_counts[topic] += 1
        emphasis_signal_counts[topic]["headings"] += int(is_heading)
        emphasis_signal_counts[topic]["definitions"] += int(passage["definition"])
        emphasis_signal_counts[topic]["lists"] += int(is_list)
        emphasis_signal_counts[topic]["emphasized_terms"] += len(emphasized_in_passage)
        emphasis_signal_counts[topic]["repeated_terms"] += len(repeated_in_passage)
        tokens = clean_text(passage["text"]).split()
        repeated = sum(max(0, frequencies[token] - 1) for token in set(tokens))
        emphasized_count = sum(emphasized[token] for token in set(tokens))
        emphasis_scores[topic] += (
            0.25 * tfidf_weights[passage_index] / maximum_tfidf
            + (0.20 if is_heading else 0.0)
            + (0.20 if passage["definition"] else 0.0)
            + (0.10 if is_list else 0.0)
            + 0.10 * min(1.0, repeated / max(1, len(set(tokens))))
            + 0.15 * min(1.0, emphasized_count / max(1, len(set(tokens))))
            + 0.10 * sum(frequencies[token] / maximum_frequency for token in set(tokens))
              / max(1, len(set(tokens)))
        )

    maximum_emphasis = max(emphasis_scores.values(), default=0.0)
    if maximum_emphasis:
        emphasis_scores = {
            topic: score / maximum_emphasis
            for topic, score in emphasis_scores.items()
        }

    exam_counts = Counter()
    exam_questions_by_topic: dict[str, list[str]] = {}
    all_exam_question_lines = []
    for source in exam_sources:
        exam_text = str(source.get("text", ""))
        source_passages = _lesson_passages(exam_text)
        source_distributions = compat_questions.predict_distributions(
            [passage["text"] for passage in source_passages],
            training_examples,
        ) if source_passages else []
        file_topics = set()
        for passage, distribution in zip(source_passages, source_distributions):
            classified = compat_questions.classify_with_policy(
                passage["text"],
                training_examples,
                dataset_id,
                policy,
                distribution,
            )
            if classified["topic"] != "Unclassified":
                file_topics.add(classified["topic"])
        exam_counts.update(file_topics)
        for line in exam_text.splitlines():
            line = line.strip(" \t-•")
            if len(line) >= 24 and (
                "?" in line
                or re.match(
                    r"^(?:what|which|who|when|where|why|how|define|explain|describe|"
                    r"compare|list|state|identify|discuss)\b",
                    line,
                    re.IGNORECASE,
                )
            ) and clean_text(line):
                all_exam_question_lines.append(line)
                if len(all_exam_question_lines) >= 500:
                    break
    if all_exam_question_lines:
        exam_question_distributions = compat_questions.predict_distributions(
            all_exam_question_lines, training_examples
        )
        for line, distribution in zip(all_exam_question_lines, exam_question_distributions):
            classified = compat_questions.classify_with_policy(
                line,
                training_examples,
                dataset_id,
                policy,
                distribution,
            )
            if classified["topic"] != "Unclassified":
                exam_questions_by_topic.setdefault(classified["topic"], []).append(line)
    has_exam_evidence = bool(exam_sources)
    maximum_exam_count = max(exam_counts.values(), default=1)
    recent = Counter(topic.casefold() for topic in recent_question_topics)
    style_by_topic = dict.fromkeys(topics, 0.0)
    style_by_question = {}
    if exam_questions_by_topic and questions:
        exam_lines = [
            (topic, line)
            for topic, lines in exam_questions_by_topic.items()
            for line in lines[:200]
        ]
        vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        try:
            matrix = vectorizer.fit_transform(
                [item["question_text"] for item in questions]
                + [line for _, line in exam_lines]
            )
            similarities = cosine_similarity(
                matrix[:len(questions)],
                matrix[len(questions):],
            )
            topic_scores = {topic: [] for topic in topics}
            for question_index, item in enumerate(questions):
                matching = [
                    similarities[question_index, index]
                    for index, (topic, _) in enumerate(exam_lines)
                    if topic == item["topic"]
                ]
                style_by_question[item["id"]] = max(matching, default=0.0)
                if matching:
                    topic_scores[item["topic"]].append(max(matching))
            for topic in topics:
                style_by_topic[topic] = max(topic_scores[topic], default=0.0)
        except ValueError:
            style_by_question = {}

    topic_scores = []
    for topic in topics:
        exam_frequency = exam_counts[topic] / maximum_exam_count
        gap = (
            1.0 if exam_counts[topic] and recent[topic.casefold()] == 0 else 0.0
        )
        if has_exam_evidence:
            score = (
                0.40 * exam_frequency
                + 0.30 * emphasis_scores.get(topic, 0.0)
                + 0.20 * style_by_topic.get(topic, 0.0)
                + 0.10 * gap
            )
        else:
            score = emphasis_scores.get(topic, 0.0)
        explanations = []
        signals = emphasis_signal_counts[topic]
        emphasis_reasons = []
        for key, label in (
            ("headings", "heading"),
            ("definitions", "definition"),
            ("lists", "list"),
        ):
            if signals[key]:
                emphasis_reasons.append(f"{signals[key]} lesson {label}(s)")
        if signals["emphasized_terms"]:
            emphasis_reasons.append("emphasized key terms")
        if signals["repeated_terms"]:
            emphasis_reasons.append("repeated key terms")
        if emphasis_scores.get(topic, 0.0) > 0:
            emphasis_reasons.append("TF-IDF term emphasis")
        if emphasis_reasons:
            explanations.append("Lesson emphasis: " + ", ".join(emphasis_reasons))
        if has_exam_evidence:
            explanations.append(
                f"Appeared in {exam_counts[topic]} past exam file(s)"
                if exam_counts[topic]
                else "Not classified in uploaded past exams"
            )
            if gap:
                explanations.append("No recent saved practice question for this exam topic")
            if style_by_topic.get(topic, 0.0) >= 0.2:
                explanations.append("Lesson questions resemble past-exam wording")
        else:
            explanations.append("Ranked by lesson emphasis; no past exam PDFs found")
        topic_scores.append(
            {
                "topic": topic,
                "likelihood_score": round(score, 4),
                "likelihood": _likelihood_label(score),
                "why": explanations,
                "lesson_passages": topic_passage_counts[topic],
                "exam_files": exam_counts[topic],
            }
        )
    topic_scores.sort(
        key=lambda item: (-item["likelihood_score"], item["topic"].casefold())
    )
    topic_score_by_name = {item["topic"]: item for item in topic_scores}

    for item in questions:
        topic_score = topic_score_by_name.get(item["topic"])
        item["likelihood_score"] = (
            topic_score["likelihood_score"] if topic_score else 0.0
        )
        item["likelihood"] = topic_score["likelihood"] if topic_score else "Low"
        item["likelihood_why"] = list(topic_score["why"]) if topic_score else [
            "Question topic could not be classified from the lesson"
        ]
        style_score = style_by_question.get(item["id"], 0.0)
        if style_score >= 0.2:
            item["likelihood_why"].append("Question wording resembles a past-exam item")
        elif has_exam_evidence:
            item["likelihood_why"].append("No strong past-exam wording match")
        if has_exam_evidence and style_by_question:
            item["likelihood_score"] = round(
                0.8 * item["likelihood_score"] + 0.2 * style_score, 4
            )
            item["likelihood"] = _likelihood_label(item["likelihood_score"])

    return {
        "lesson_analysis": {
            "passages": analyzed_passages,
            "unclassified_count": sum(
                passage["topic"] == "Unclassified" for passage in analyzed_passages
            ),
        },
        "likely_topics": topic_scores,
        "exam_evidence_available": has_exam_evidence,
        "exam_sources": [str(source.get("name", "")) for source in exam_sources],
        "ranking_formula": (
            {
                "past_exam_frequency": 0.40,
                "lesson_emphasis": 0.30,
                "exam_style_similarity": 0.20,
                "coverage_gap": 0.10,
            }
            if has_exam_evidence else {"lesson_emphasis": 1.0}
        ),
        "disclaimer": (
            "Likelihood is an estimate from your materials, not a guarantee of actual exam content."
        ),
    }

def _likelihood_label(score: float) -> str:
    if score >= 0.67:
        return "High"
    if score >= 0.34:
        return "Medium"
    return "Low"

def estimate_difficulty(sentence: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", sentence)
    cues = {word.casefold() for word in words} & _COMPLEXITY_CUES
    if len(words) <= 12:
        return "Easy"
    if len(words) >= 36 or len(cues) >= 2:
        return "Difficult"
    return "Moderate"

def topic_priority(
    topics: Sequence[str],
    training_examples: Sequence[tuple[str, str]],
    material_texts: Sequence[str],
    topic_confidence: Mapping[str, float],
    weights: Mapping[str, float] | None = None,
) -> list[dict]:
    weights = validate_weights(weights)
    counts = Counter(topic.strip() for _, topic in training_examples if topic.strip())
    max_frequency = max(counts.values(), default=1)
    all_material = "\n".join(material_texts).casefold()
    material_counts: dict[str, int] = {}
    for topic in topics:
        words = [word for word in re.findall(r"[a-z0-9]+", topic.casefold()) if len(word) > 1]
        material_counts[topic] = sum(
            len(re.findall(rf"\b{re.escape(word)}\b", all_material)) for word in words
        )
    max_material = max(material_counts.values(), default=0)

    ranked = []
    for topic in topics:
        frequency_score = counts[topic] / max_frequency
        material_score = (
            material_counts[topic] / max_material if max_material else 0.0
        )
        confidence_score = max(0.0, min(1.0, float(topic_confidence.get(topic, 0.0))))
        recent_score = 0.5
        score = (
            frequency_score * weights["historical_frequency"]
            + material_score * weights["course_importance"]
            + confidence_score * weights["model_confidence"]
            + recent_score * weights["recent_occurrence"]
        )
        ranked.append(
            {
                "topic": topic,
                "priority_score": round(score, 4),
                "frequency_score": round(frequency_score, 4),
                "course_importance_score": round(material_score, 4),
                "model_confidence_score": round(confidence_score, 4),
                "recent_occurrence_score": recent_score,
                "recent_occurrence_available": False,
            }
        )
    return sorted(ranked, key=lambda item: (-item["priority_score"], item["topic"].casefold()))

def is_duplicate(candidate: str, previous: Sequence[str], threshold: float) -> bool:
    if not previous:
        return False
    documents = [candidate, *previous]
    matrix = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5)).fit_transform(
        documents
    )
    return bool(cosine_similarity(matrix[0:1], matrix[1:]).max() >= threshold)
