from __future__ import annotations

import re
from pathlib import Path


def _is_exam_upload(row) -> bool:
    if row["is_exam"] is not None:
        return bool(row["is_exam"])
    return (
        Path(row["name"]).suffix.lower() in {".pdf", ".docx", ".txt"}
        and re.search(r"(?:^|[_\s-])exam(?:[_\s.-]|$)", row["name"], re.I) is not None
    )
