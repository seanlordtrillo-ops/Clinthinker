from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from .true_false import clean_statement

_DEFINITION = re.compile(
    r"^\s*(?:(?:a|an|the)\s+)?"
    r"([A-Za-z][A-Za-z0-9/-]*(?:\s+[A-Za-z][A-Za-z0-9/-]*){0,3})\s+"
    r"(?:is defined as|is|are|refers to|means|describes)\s+(.{12,300})$",
    re.IGNORECASE,
)
_INVALID_TERM_STARTS = {
    "analyze", "because", "compare", "define", "describe", "discuss", "explain",
    "how", "identify", "list", "locally", "select", "state", "what", "when",
    "where", "which", "who", "why",
}
_DISTRACTOR_JUNK = ENGLISH_STOP_WORDS | {
    "all values", "code", "concept", "data", "example", "information", "item",
    "object", "passage", "process", "result", "source", "stuff", "system", "text",
    "thing", "type", "value", "values", "way", "you",
}
_PRONOUNS = {
    "he", "her", "hers", "herself", "him", "himself", "his", "i", "it", "its",
    "itself", "me", "my", "myself", "our", "ours", "ourselves", "she", "them",
    "themselves", "they", "us", "we", "you", "your", "yours", "yourself",
    "yourselves",
}
_INVALID_TERM_ADJECTIVES = {
    "basic", "common", "effective", "essential", "good", "important", "key",
    "main", "necessary", "proper",
}
_UNCOUNTABLE_NOUNS = {"data", "equipment", "hardware", "information", "software"}
_KNOWN_ACRONYMS = {
    "ACL", "ALU", "API", "BIOS", "CPU", "DHCP", "DNS", "FCAPS", "GPU",
    "HDMI", "HDD", "HTTP", "HTTPS", "ISO", "IP", "MIB", "NIC", "NMS",
    "NVMe", "OID", "PCIe", "PSU", "RAID", "RAM", "REST", "RJ-45", "ROM",
    "SATA", "SDN", "SLA", "SNMP", "SSD", "SSH", "TCP", "UEFI", "UDP",
    "USB", "USB-C", "WAN", "YANG",
}
_KNOWN_PROPER_NOUNS = {
    "Amazon", "Ansible", "Apple", "Google", "Intel", "Microsoft", "NVIDIA",
}
_KNOWN_PROPER_NOUN_PHRASES = {
    "Amazon Web Services", "Google Cloud", "Microsoft Azure",
}
_FOLDED_ACRONYMS = {item.casefold() for item in _KNOWN_ACRONYMS}
_INCOMPLETE_ENDINGS = re.compile(
    r"\b(?:a|an|and|are|as|because|but|by|for|from|in|is|of|or|that|the|to|"
    r"was|were|which|with)$",
    re.IGNORECASE,
)

_APPOSITIVE = re.compile(
    r"^(?:(?:a|an|the)\s+)?[A-Za-z][\w /-]{2,60}?,\s+or\s+([A-Z][\w-]{1,10}),\s+(?=(?:is|are)\s)"
)
_NOT_A_DEFINITION_START = re.compile(
    r"^(?:also|much|more|less|faster|slower|about|measured|made|often|usually|very)\b",
    re.IGNORECASE,
)


class _Description(str):
    """Explanation taken from a "Term — description" line.

    Lessons often list definitions as "Persona — a fictional user profile" or
    "Closure — the mind completes incomplete shapes". The text after the dash can be
    a noun phrase or a whole clause, so these get wording that works for both.
    """


_DASH_DEFINITION = re.compile(
    r"^(?P<term>[A-Z][\w'’/&+.-]*(?:\s+[\w'’/&+.-]+){0,3}(?:\s+\([^()]{1,40}\))?)"
    r"\s+(?:—|–|--|-)\s+(?P<explanation>[^—–]{12,300})$"
)


_DOCUMENT_PART_WORDS = {
    "activity", "chapter", "figure", "lecture", "lesson", "module", "page", "part",
    "section", "step", "table", "topic", "unit", "week",
}


def _dash_definition(sentence: str) -> tuple[str, str] | None:
    """Read a "Term — description" line (em dash, en dash or spaced hyphen)."""
    match = _DASH_DEFINITION.match(sentence.strip().rstrip("."))
    if not match:
        return None
    term = re.sub(r"\s+", " ", match.group("term")).strip()
    explanation = re.sub(r"\s+", " ", match.group("explanation")).strip()
    core_words = re.sub(r"\s*\([^()]*\)", "", term).split()
    explanation_words = re.findall(r"[A-Za-z][\w'’-]*", explanation)
    title_case_words = sum(word[0].isupper() for word in explanation_words)
    if (
        len(term) < 3
        or not core_words
        or core_words[0].casefold() in _INVALID_TERM_STARTS
        # Headings such as "Chapter 2 - Introduction to Computer Hardware" are not definitions.
        or core_words[0].casefold() in _DOCUMENT_PART_WORDS
        or any(word.isdigit() for word in core_words)
        or title_case_words >= max(2, 0.6 * len(explanation_words))
        or len(explanation.split()) < 3
        or '"' in explanation
        or _INCOMPLETE_ENDINGS.search(explanation.rstrip(".!?"))
    ):
        return None
    return term, _Description(explanation)


def _definition(sentence: str) -> tuple[str, str] | None:
    # "The central processing unit, or CPU, is ..." -> "CPU is ..."
    sentence = _APPOSITIVE.sub(lambda m: m.group(1) + " ", sentence.strip())
    match = _DEFINITION.match(sentence.strip().rstrip("."))
    if not match:
        return _dash_definition(sentence)
    term = re.sub(r"\s+", " ", match.group(1)).strip(" -")
    explanation = re.sub(r"\s+", " ", match.group(2)).strip()
    term_words = term.split()
    if (
        len(term) < 3
        or len(term_words) > 4
        or any(len(word) < 3 and not word.isupper() for word in term_words)
        or term_words[0].casefold() in _INVALID_TERM_STARTS
        or term_words[0].casefold() in _INVALID_TERM_ADJECTIVES
        or len(explanation) < 12
        or _INCOMPLETE_ENDINGS.search(explanation.rstrip(".!?"))
        or term.casefold() == explanation.casefold()
        or _NOT_A_DEFINITION_START.match(explanation)
    ):
        return None
    return term, explanation

def _definition_category(explanation: str) -> str:
    normalized = re.sub(r"\s+", " ", explanation).strip().rstrip(".!?").casefold()
    example = re.match(r"^(?:an?|the)\s+examples?\s+of\s+(.+)$", normalized)
    if example:
        target = example.group(1).rstrip("s")
        if "cloud provider" in target:
            return "organization"
        return "example"
    if re.match(
        r"^(?:an?\s+|the\s+)?(?:company|organization|provider)\b",
        normalized,
    ):
        return "organization"
    if re.match(r"^(?:an?\s+|the\s+)?facility\b", normalized):
        return "facility"
    headword = _definition_headword(normalized)
    defining_phrase = re.split(
        r"\b(?:that|which|who|in which|where|when)\b",
        normalized,
        maxsplit=1,
    )[0]
    if "storage" in defining_phrase and headword in {
        "device", "drive", "interface", "medium", "protocol", "technology",
    }:
        return "storage_technology"
    if headword in {"bus", "technology"} and "storage" in normalized:
        return "storage_technology"
    if headword in {
        "component", "device", "hardware", "part", "peripheral",
    }:
        return "physical_component"
    if headword in {"act", "method", "practice", "process", "technique"}:
        return "process"
    if headword in {"rule", "protocol", "standard"}:
        return "protocol"
    return headword

def _singularize_headword(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return f"{word[:-3]}y"
    if word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        return word[:-1]
    return word

def _definition_headword(explanation: str) -> str:
    normalized = re.sub(r"\s+", " ", explanation).strip().rstrip(".!?").casefold()
    normalized = re.sub(r"^(?:a|an|the)\s+", "", normalized)
    if re.match(r"^unit\s+of\s+", normalized):
        return "unit"
    if re.match(r"^collection\s+of\s+(?:physical\s+)?components?\b", normalized):
        return "physical_component"
    phrase = re.split(
        r"\b(?:that|which|who|in which|where|when|used to|designed to|located)\b",
        normalized,
        maxsplit=1,
    )[0].strip()
    words = re.findall(r"[a-z0-9-]+", phrase)
    if not words:
        return "concept"
    headword = _singularize_headword(words[-1])
    return headword

def _article_for(word: str) -> str:
    folded = word.casefold()
    if folded.startswith(("uni", "use", "user", "euro", "one", "once")):
        return "a"
    if folded.startswith(("hour", "honest", "honor", "heir")):
        return "an"
    if folded in _FOLDED_ACRONYMS:
        return "an" if word[:1].upper() in {
            "A", "E", "F", "H", "I", "L", "M", "N", "O", "R", "S", "X",
        } else "a"
    return "an" if folded[:1] in "aeiou" else "a"

def _correct_indefinite_articles(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        article, word = match.groups()
        if word.casefold() in _UNCOUNTABLE_NOUNS:
            return word.capitalize() if article[:1].isupper() else word
        corrected = _article_for(word)
        if article[:1].isupper():
            corrected = corrected.capitalize()
        return f"{corrected} {word}"

    return re.sub(r"\b(an?)\s+([A-Za-z][A-Za-z0-9-]*)", replace, text, flags=re.IGNORECASE)

def _normalize_choice(term: str) -> str:
    if term in _KNOWN_PROPER_NOUN_PHRASES:
        return term
    words = term.split()
    normalized = []
    for word in words:
        clean_word = word.strip(".,;:()[]{}")
        if (
            clean_word.casefold() in _FOLDED_ACRONYMS
            or clean_word in _KNOWN_PROPER_NOUNS
            or any(character.isdigit() for character in clean_word)
            or not clean_word.isupper()
            and any(character.isupper() for character in clean_word[1:])
        ):
            normalized.append(word)
        else:
            normalized.append(word.lower())
    if normalized:
        normalized[0] = normalized[0][:1].upper() + normalized[0][1:]
    return " ".join(normalized)

def _is_concept_term(term: str) -> bool:
    normalized = re.sub(r"\s+", " ", term).strip().casefold()
    words = normalized.split()
    return (
        len(words) <= 4
        and len(normalized) >= 3
        and normalized not in _DISTRACTOR_JUNK
        and not any(word in _DISTRACTOR_JUNK for word in words)
        and not any(word in _PRONOUNS for word in words)
    )

def _stem_article(category: str) -> str:
    """Return "a " for a stem, or "" when the category is plural or an -ing word."""
    first = category.split()[0].casefold()
    if first.endswith("ing") or (first.endswith("s") and not first.endswith(("ss", "us", "is"))):
        return ""
    return "a "


def _question_from_definition_raw(term: str, explanation: str, order: int) -> str | None:
    if isinstance(explanation, _Description):
        return f'Which term matches this description: "{explanation.rstrip(".!?")}"?'
    explanation = re.sub(r"\s+", " ", explanation).strip().rstrip(".!?")
    example = re.fullmatch(r"(?:an?|the)\s+example\s+of\s+(.+)", explanation, re.IGNORECASE)
    if example:
        return f"Which of the following is an example of {example.group(1).strip()}?"

    rules = re.match(
        r"^(?:a|an|the)\s+(?:formal\s+)?set\s+of\s+rules\s+that\s+"
        r"(?:govern|governs)\s+(.+)$",
        explanation,
        re.IGNORECASE,
    )
    if rules:
        headword = term.split()[-1].casefold()
        return f"Which {headword} governs {rules.group(1).rstrip('.!?')}?"

    organization = re.match(
        r"^(?:a|an|the)\s+(?:company|organization)\s+that\s+(.+)$",
        explanation,
        re.IGNORECASE,
    )
    if organization:
        return (
            "Which term refers to an organization that "
            f"{organization.group(1).strip().rstrip('.!?')}?"
        )

    in_which_clause = re.match(
        r"^(?:(?:a|an|the)\s+)?(?P<category>[\w-]+(?:\s+[\w-]+){0,4}?)\s+"
        r"(?P<connector>in which|where|when)\s+(?P<clause>.+)$",
        explanation,
        re.IGNORECASE,
    )
    if in_which_clause:
        category = in_which_clause.group("category").strip()
        connector = in_which_clause.group("connector").casefold()
        clause = in_which_clause.group("clause").strip().rstrip(".!?")
        return f"Which term describes {_stem_article(category)}{category} {connector} {clause}?"

    relative_clause = re.match(
        r"^(?:(?:a|an|the)\s+)?(?P<category>[\w-]+(?:\s+[\w-]+){0,4}?)\s+"
        r"(?:that|which|who)\s+(?P<clause>.+)$",
        explanation,
        re.IGNORECASE,
    )
    if relative_clause:
        category = relative_clause.group("category").strip()
        clause = relative_clause.group("clause").strip().rstrip(".!?")
        if category.casefold().split()[-1] in {"in", "of", "on", "to", "at", "for"}:
            return None
        if category.casefold() in {"research", "study"}:
            return f"Which type of {category} {clause}?"
        return f"Which term describes {_stem_article(category)}{category} that {clause}?"

    instrument = re.match(
        r"^(?:a|an|the)\s+(?P<category>instrument|tool|method)\s+"
        r"(?:that\s+)?(?:is\s+)?used\s+to\s+(?P<action>.+)$",
        explanation,
        re.IGNORECASE,
    )
    if instrument:
        category = instrument.group("category").casefold()
        action = instrument.group("action").strip().rstrip(".!?")
        return f"Which {category} is used to {action}?"

    process = re.match(
        r"^(?:the\s+)?(?P<category>process|practice|act)\s+of\s+(?P<action>.+)$",
        explanation,
        re.IGNORECASE,
    )
    if process:
        category = process.group("category").casefold()
        action = process.group("action").strip().rstrip(".!?")
        return f"Which {category} involves {action}?"

    variable = re.search(
        r"\bvariable\s+(?:that\s+is\s+)?manipulated\s+by\s+(?:the\s+)?researcher\b",
        explanation,
        re.IGNORECASE,
    )
    if variable:
        return "Which variable does the researcher deliberately change?"

    delivery = re.match(r"^the\s+delivery\s+of\s+(.+)$", explanation, re.IGNORECASE)
    if delivery:
        return f"Which term describes the delivery of {delivery.group(1).strip()}?"

    technology = re.match(
        r"^(?:the\s+)?technology\s+that\s+(.+)$", explanation, re.IGNORECASE
    )
    if technology:
        return f"Which term describes the technology that {technology.group(1).strip()}?"

    ability = re.match(
        r"^(?:the\s+)?ability\s+of\s+(.+)$", explanation, re.IGNORECASE
    )
    if ability:
        return f"Which term describes the ability of {ability.group(1).strip()}?"

    return None

def _question_from_definition(term: str, explanation: str, order: int) -> str | None:
    question = _question_from_definition_raw(term, explanation, order)
    return _correct_indefinite_articles(question) if question else None

def _statement_from_definition_raw(term: str, explanation: str) -> str:
    if isinstance(explanation, _Description):
        return f"{term} means: {explanation.rstrip('.!?')}."
    explanation = re.sub(r"\s+", " ", explanation).strip().rstrip(".!?")
    folded_term = term.casefold()
    if "independent variable" in folded_term:
        return "The researcher changes the independent variable to test its effect on the outcome."
    if "dependent variable" in folded_term:
        return "The researcher measures the dependent variable to observe the study's outcome."
    if "quantitative research" in folded_term:
        return "A study that analyzes numerical measurements follows a quantitative approach."
    if "qualitative research" in folded_term:
        return "A study that interprets participants' experiences follows a qualitative approach."
    if "questionnaire" in folded_term:
        return "A researcher collecting opinions from a large group can use a questionnaire."

    instrument = re.match(
        r"^(?:a|an|the)\s+(?:instrument|tool|method)\s+"
        r"(?:that\s+)?(?:is\s+)?used\s+to\s+(.+)$",
        explanation,
        re.IGNORECASE,
    )
    if instrument:
        article = "an" if term[0].casefold() in "aeiou" else "a"
        return (
            f"A researcher who needs to {instrument.group(1).rstrip('.!?')} "
            f"can use {article} {term.casefold()}."
        )

    if "router" in folded_term and "packet" in explanation.casefold():
        return "When a packet must reach another network, a router forwards it along a route."
    if "routing" in folded_term and "path" in explanation.casefold():
        return "Routing selects a path for a packet traveling across connected networks."
    if "protocol" in folded_term and "rule" in explanation.casefold():
        return "A network protocol helps devices follow shared communication rules."
    if "packet switching" in folded_term:
        return "A network that sends data in small units is using packet switching."

    relative_clause = re.match(
        r"^(?:(?:a|an|the)\s+)?(?P<category>[\w -]{2,45}?)\s+"
        r"(?:that|which|who)\s+(?P<clause>.+)$",
        explanation,
        re.IGNORECASE,
    )
    # "designing so that people can use it" has its own subject after "that", so it
    # cannot become "<Term> people can use it"; it falls through to the general wording.
    if relative_clause and not re.search(
        r"\b(?:so|such)$", relative_clause.group("category"), re.IGNORECASE
    ):
        clause = relative_clause.group("clause").strip().rstrip(".!?")
        subject = term[0].upper() + term[1:]
        if len(term.split()) == 1 and not term.casefold().endswith(("s", "ing")):
            article = "An" if term[0].casefold() in "aeiou" else "A"
            name = term if any(character.isupper() for character in term[1:]) else term.casefold()
            subject = f"{article} {name}"
        return f"{subject} {clause[0].lower() + clause[1:]}."
    return f"{term[0].upper() + term[1:]} is associated with {explanation[0].lower() + explanation[1:]}."

def _statement_from_definition(term: str, explanation: str) -> str:
    return _correct_indefinite_articles(
        _statement_from_definition_raw(term, explanation)
    )
