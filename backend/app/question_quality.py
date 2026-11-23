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




def definition_record(
    sentence: str,
    *,
    source_id: str = "",
    source_kind: str = "",
    topic: str = "",
) -> dict | None:
    match = _DEFINITION.match(sentence.strip().rstrip("."))
    if not match:
        dash = _dash_definition(sentence)
        if not dash:
            return None
        # "means:" matches the wording of _statement_from_definition for dash lines,
        # so true/false swaps only borrow from other "Term — description" lines.
        return {
            "term": dash[0],
            "verb": "means:",
            "explanation": str(dash[1]),
            "source_id": source_id,
            "source_kind": source_kind,
            "topic": topic,
        }
    return {
        "term": re.sub(r"\s+", " ", match.group("term")).strip(),
        "verb": re.sub(r"\s+", " ", match.group("verb")).casefold(),
        "explanation": re.sub(r"\s+", " ", match.group("explanation")).strip(),
        "source_id": source_id,
        "source_kind": source_kind,
        "topic": topic,
    }

from .definitions import _dash_definition
from .distractors import rank_distractors
from .true_false import clean_statement, swap_false_statement
