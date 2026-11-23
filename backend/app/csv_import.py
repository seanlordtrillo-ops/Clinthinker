"""Flexible reader for labeled CSV training data.

Accepts most CSV files people produce with Excel, Google Sheets or a text editor:
any common separator, several encodings, title rows above the header, different
column names, no header at all, blank rows, and unquoted separators inside the text.
"""

from __future__ import annotations

import csv
import io
import re
from statistics import mean

MAX_CSV_ROWS = 50000
HEADER_SEARCH_ROWS = 10

TOPIC_NAMES = {
    "topic", "topics", "topic label", "topic name", "label", "labels", "category",
    "categories", "class", "classes", "subject", "subjects", "tag", "tags", "lesson",
    "module", "unit", "chapter",
}
TEXT_NAMES = {
    "text", "texts", "content", "contents", "sentence", "sentences", "example",
    "examples", "description", "descriptions", "definition", "definitions", "passage",
    "passages", "body", "statement", "statements", "question", "questions", "material",
    "details", "explanation", "paragraph",
}
DELIMITER_NAMES = {",": "comma", ";": "semicolon", "\t": "tab", "|": "vertical bar"}


class CsvImportError(ValueError):
    """A CSV problem the user can fix. status_code is the HTTP code to send back."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def _decode(content: bytes) -> tuple[str, str]:
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16"), "UTF-16"
    try:
        return content.decode("utf-8-sig"), "UTF-8"
    except UnicodeDecodeError:
        pass
    if b"\x00" in content[:4000]:
        for encoding in ("utf-16-le", "utf-16-be"):
            try:
                return content.decode(encoding), "UTF-16"
            except UnicodeDecodeError:
                continue
    try:
        return content.decode("cp1252"), "Windows-1252"
    except UnicodeDecodeError:
        return content.decode("latin-1"), "Latin-1"


def _detect_delimiter(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()][:30]
    sample = "\n".join(lines)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        pass
    counts = {
        delimiter: sum(line.count(delimiter) for line in lines)
        for delimiter in DELIMITER_NAMES
    }
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _find_header(rows: list[list[str]]) -> tuple[int, int, int] | None:
    """Return (row index, topic column, text column) of a recognizable header row."""
    for row_index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        names = [_normalize_name(cell) for cell in row]
        topic_columns = [i for i, name in enumerate(names) if name in TOPIC_NAMES]
        text_columns = [i for i, name in enumerate(names) if name in TEXT_NAMES]
        if not topic_columns or not text_columns:
            continue
        # Prefer the exact names "topic" and "text" when several columns qualify.
        topic = next((i for i in topic_columns if names[i] == "topic"), topic_columns[0])
        text = next((i for i in text_columns if names[i] == "text" and i != topic), None)
        if text is None:
            text = next((i for i in text_columns if i != topic), None)
        if text is not None:
            return row_index, topic, text
    return None


def _guess_columns(rows: list[list[str]]) -> tuple[int, int, bool]:
    """Guess (topic column, text column, first row is a header) from the data itself."""
    width = max(len(row) for row in rows)
    if width < 2:
        raise CsvImportError(
            "The CSV needs at least two columns: one for the topic and one for the text."
        )
    body = rows[1:] if len(rows) > 2 else rows
    columns = []
    for index in range(width):
        values = [row[index].strip() for row in body if index < len(row) and row[index].strip()]
        if not values:
            continue
        columns.append({
            "index": index,
            "average_length": mean(len(value) for value in values),
            "distinct_ratio": len(set(values)) / len(values),
            "distinct": len(set(values)),
        })
    if len(columns) < 2:
        raise CsvImportError(
            "Could not find both a topic column and a text column in the CSV. "
            "Add a header row with 'topic' and 'text'."
        )
    text_column = max(columns, key=lambda column: column["average_length"])
    candidates = [
        column for column in columns
        if column is not text_column and column["distinct"] >= 2 and column["average_length"] <= 80
    ] or [column for column in columns if column is not text_column]
    topic_column = min(candidates, key=lambda column: (column["distinct_ratio"], column["average_length"]))
    topic, text = topic_column["index"], text_column["index"]

    first = rows[0]
    first_text = first[text].strip() if text < len(first) else ""
    first_topic = first[topic].strip() if topic < len(first) else ""
    other_topics = {row[topic].strip() for row in rows[1:] if topic < len(row)}
    header_like = (
        len(rows) > 2
        and first_topic not in other_topics
        and len(first_text) < 0.5 * text_column["average_length"]
    )
    return topic, text, header_like


def _cells_for(row: list[str], width: int, topic: int, text: int, delimiter: str) -> tuple[str, str, bool]:
    """Read topic and text from a row; join extra pieces back into the text column."""
    extra = len(row) - width
    if extra > 0:
        text_value = delimiter.join(row[text:text + extra + 1])
        topic_index = topic + extra if topic > text else topic
        return row[topic_index], text_value, True
    topic_value = row[topic] if topic < len(row) else ""
    text_value = row[text] if text < len(row) else ""
    return topic_value, text_value, False


def read_labeled_csv(content: bytes) -> tuple[list[tuple[str, str]], dict]:
    """Return (examples as (text, topic) pairs, a summary of what was detected)."""
    decoded, encoding = _decode(content)
    decoded = decoded.replace("\r\n", "\n").replace("\r", "\n")
    delimiter = _detect_delimiter(decoded)
    try:
        rows = list(csv.reader(io.StringIO(decoded), delimiter=delimiter))
    except csv.Error as error:
        raise CsvImportError(f"Could not read the CSV rows: {error}") from error
    rows = [row for row in rows if any(cell.strip() for cell in row)]
    if not rows:
        raise CsvImportError("The CSV file has no rows.")

    header = _find_header(rows)
    if header:
        header_index, topic, text = header
        header_row = rows[header_index]
        width = len(header_row)
        data = rows[header_index + 1:]
        topic_name, text_name = header_row[topic].strip(), header_row[text].strip()
        guessed = False
        header_line = header_index + 1
    else:
        topic, text, has_header = _guess_columns(rows)
        width = max(topic, text) + 1
        common_width = max(set(len(row) for row in rows), key=[len(row) for row in rows].count)
        width = max(width, common_width)
        data = rows[1:] if has_header else rows
        if has_header:
            topic_name = rows[0][topic].strip() or f"column {topic + 1}"
            text_name = rows[0][text].strip() or f"column {text + 1}"
            header_line = 1
        else:
            topic_name, text_name, header_line = f"column {topic + 1}", f"column {text + 1}", None
        guessed = True

    examples: list[tuple[str, str]] = []
    skipped = repaired = 0
    for row in data:
        topic_value, text_value, joined = _cells_for(row, width, topic, text, delimiter)
        topic_value, text_value = topic_value.strip(), text_value.strip()
        if not topic_value or not text_value:
            skipped += 1
            continue
        repaired += joined
        examples.append((text_value, topic_value))
        if len(examples) > MAX_CSV_ROWS:
            raise CsvImportError("CSV datasets are limited to 50,000 rows.", status_code=413)

    if not examples:
        raise CsvImportError(
            "No rows had both a topic and a text. Check that the CSV has a topic column and a text column."
        )
    info = {
        "encoding": encoding,
        "delimiter": DELIMITER_NAMES.get(delimiter, repr(delimiter)),
        "header_row": header_line,
        "topic_column": topic_name,
        "text_column": text_name,
        "columns_guessed": guessed,
        "rows_imported": len(examples),
        "rows_skipped": skipped,
        "rows_repaired": repaired,
    }
    return examples, info
