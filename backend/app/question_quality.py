from __future__ import annotations

import re
from collections.abc import Mapping, Sequence


_DEFINITION = re.compile(
    r"^\s*(?:(?:a|an|the)\s+)?"
    r"(?P<term>[A-Za-z][A-Za-z0-9/-]*(?:\s+[A-Za-z][A-Za-z0-9/-]*){0,3})\s+"
    r"(?P<verb>is defined as|is|are|refers to|means|describes)\s+"
    r"(?P<explanation>.{12,300})$",
    re.IGNORECASE,
)
_DANGLING_WORDS = {
    "a", "an", "and", "are", "as", "because", "but", "by", "for", "from",
    "in", "is", "of", "or", "that", "the", "to", "was", "were", "which",
    "with",
}
_SINGULAR_NOUN_EXCEPTIONS = {
    "analysis", "business", "gas", "mathematics", "news", "physics", "series",
    "species", "status",
}
_VERBS = {
    "am", "is", "are", "was", "were", "be", "been", "being", "has", "have",
    "had", "do", "does", "did", "can", "could", "will", "would", "should",
    "must", "may", "might", "refer", "refers", "referred", "mean", "means",
    "meant", "describe", "describes", "described", "define", "defines", "defined",
    "represent", "represents", "represented", "consist", "consists", "include",
    "includes", "included", "contain", "contains", "contained", "use", "uses",
    "used", "allow", "allows", "allowed", "provide", "provides", "provided",
    "connect", "connects", "connected", "forward", "forwards", "forwarded",
    "filter", "filters", "filtered", "store", "stores", "stored", "send", "sends",
    "sent", "transfer", "transfers", "transferred", "measure", "measures",
    "measured", "collect", "collects", "collected", "control", "controls",
    "controlled", "select", "selects", "selected", "help", "helps", "helped",
    "create", "creates", "created", "compute", "computes", "computed", "produce",
    "produces", "produced", "serve", "serves", "served", "deliver", "delivers",
    "delivered", "work", "works", "worked", "communicate", "communicates",
    "communicated", "establish", "establishes", "established", "manage", "manages",
    "managed", "organize", "organizes", "organized", "require", "requires",
    "required", "depend", "depends", "depended", "occur", "occurs", "occurred",
    "change", "changes", "changed", "test", "tests", "tested", "identify",
    "identifies", "identified", "adapt", "adapts", "adapted", "run", "runs",
    "ran", "form", "forms", "formed", "belong", "belongs", "belonged", "become",
    "becomes", "became", "exist", "exists", "existed", "cause", "causes", "caused",
    "analyze", "analyzes", "analyzed", "analyzing", "interpret", "interprets",
    "interpreted", "interpreting", "follow", "follows", "followed", "observe",
    "observes", "observed", "manipulate", "manipulates", "manipulated", "present",
    "presents", "presented", "execute", "executes", "executed", "perform",
    "performs", "performed", "govern", "governs", "governed", "maintain",
    "maintains", "maintained", "enable", "enables", "enabled", "reduce", "reduces",
    "reduced", "increase", "increases", "increased", "decrease", "decreases",
    "decreased", "transmit", "transmits", "transmitted", "convert", "converts",
    "converted", "generate", "generates", "generated", "receive", "receives",
    "received", "display", "displays", "displayed", "own", "owns", "owned",
    "offer", "offers", "offered", "operate", "operates", "operated", "support",
    "supports", "supported", "interact", "interacts", "interacted", "capture",
    "captures", "captured", "analyze", "analyzes",
}
_BAD_ASSOCIATION = re.compile(
    r"\bassociated\s+with\s+(?:a|an|the\s+)?"
    r"(?:essential|necessary|important)\s+for\b",
    re.IGNORECASE,
)


def clean_statement(sentence: str) -> str | None:
    cleaned = re.sub(
        r"^\s*(?:(?:[-*•▪])\s+|\d+[.)]\s*)+",
        "",
        sentence,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned or not cleaned[0].isupper():
        return None
    if any(marker in cleaned.casefold() for marker in ("|", "…", "...", "http", "_", "\ufffd")):
        return None
    words = re.findall(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", cleaned)
    if not 6 <= len(words) <= 40:
        return None
    non_whitespace = sum(not character.isspace() for character in cleaned)
    alphabetic = sum(character.isalpha() for character in cleaned)
    if not non_whitespace or alphabetic / non_whitespace < 0.8:
        return None
    final_word = re.findall(r"[A-Za-z]+", cleaned)
    if not final_word or final_word[-1].casefold() in _DANGLING_WORDS:
        return None
    quote_pairs = {")": "(", "”": "“", "’": "‘"}
    quote_stack = []
    double_quote_open = False
    single_quote_open = False
    for index, character in enumerate(cleaned):
        if character == "(" or character in {"“", "‘"}:
            quote_stack.append(character)
        elif (
            character in {"'", "’"}
            and index > 0
            and index + 1 < len(cleaned)
            and cleaned[index - 1].isalnum()
            and cleaned[index + 1].isalnum()
        ):
            continue
        elif character in quote_pairs:
            if not quote_stack or quote_stack.pop() != quote_pairs[character]:
                return None
        elif character == '"':
            double_quote_open = not double_quote_open
        elif character == "'" and (
            index == 0 or not cleaned[index - 1].isalnum()
            or index + 1 == len(cleaned) or not cleaned[index + 1].isalnum()
        ):
            single_quote_open = not single_quote_open
    if quote_stack or double_quote_open or single_quote_open:
        return None
    if _BAD_ASSOCIATION.search(cleaned):
        return None
    singular_be = re.search(r"\b(?:is|was)\b", cleaned, re.IGNORECASE)
    if singular_be:
        subject_phrase = re.split(
            r"\b(?:that|which|who)\b",
            cleaned[:singular_be.start()],
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        subject_words = re.findall(r"[A-Za-z]+", subject_phrase)
        if subject_words:
            subject = subject_words[-1].casefold()
            if (
                subject.endswith("s")
                and not subject.endswith(("ss", "us", "is"))
                and subject not in _SINGULAR_NOUN_EXCEPTIONS
            ):
                return None
    verb_words = {word.casefold() for word in re.findall(r"[A-Za-z]+", cleaned)}
    if not (
        verb_words & _VERBS
        or any(word.endswith(("ed", "ing")) for word in verb_words)
    ):
        return None
    return cleaned.rstrip(" \t.,;:!?") + "."


def definition_record(
    sentence: str,
    *,
    source_id: str = "",
    source_kind: str = "",
    topic: str = "",
) -> dict | None:
    match = _DEFINITION.match(sentence.strip().rstrip("."))
    if not match:
        return None
    return {
        "term": re.sub(r"\s+", " ", match.group("term")).strip(),
        "verb": re.sub(r"\s+", " ", match.group("verb")).casefold(),
        "explanation": re.sub(r"\s+", " ", match.group("explanation")).strip(),
        "source_id": source_id,
        "source_kind": source_kind,
        "topic": topic,
    }


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


def swap_false_statement(
    source_definition: Mapping,
    definition_records: Sequence[Mapping],
    *,
    excluded_statements: Sequence[str] = (),
) -> tuple[str, str] | None:
    term = re.sub(r"\s+", " ", str(source_definition.get("term", ""))).strip()
    verb = re.sub(r"\s+", " ", str(source_definition.get("verb", ""))).strip()
    explanation = re.sub(
        r"\s+", " ", str(source_definition.get("explanation", ""))
    ).strip().rstrip(".!?")
    if not term or not verb or not explanation:
        return None
    source_term = term.casefold()
    source_tokens = set(re.findall(r"[a-z0-9]+", explanation.casefold()))
    excluded = {
        re.sub(r"\s+", " ", statement).strip().rstrip(".").casefold()
        for statement in excluded_statements
    }
    candidates = []
    for record in definition_records:
        other_term = re.sub(r"\s+", " ", str(record.get("term", ""))).strip()
        other_verb = re.sub(r"\s+", " ", str(record.get("verb", ""))).strip()
        other_explanation = re.sub(
            r"\s+", " ", str(record.get("explanation", ""))
        ).strip().rstrip(".!?")
        other_tokens = set(re.findall(r"[a-z0-9]+", other_explanation.casefold()))
        if (
            not other_term
            or other_term.casefold() == source_term
            or other_verb.casefold() != verb.casefold()
            or not other_explanation
            or re.search(
                rf"(?<!\w){re.escape(source_term)}(?!\w)",
                other_explanation,
                re.IGNORECASE,
            )
            or not source_tokens
            or not other_tokens
        ):
            continue
        jaccard = len(source_tokens & other_tokens) / len(source_tokens | other_tokens)
        if jaccard > 0.25:
            continue
        candidates.append(
            (
                abs(len(other_explanation) - len(explanation)),
                abs(len(other_explanation.split()) - len(explanation.split())),
                other_term.casefold(),
                other_explanation,
            )
        )
    for _, _, _, borrowed_explanation in sorted(candidates):
        statement = clean_statement(f"{term} {verb} {borrowed_explanation}")
        if statement and statement.rstrip(".").casefold() not in excluded:
            return statement, borrowed_explanation
    return None
