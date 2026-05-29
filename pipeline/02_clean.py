from __future__ import annotations

import re

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _normalize(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _CONTROL_CHARS_RE.sub("", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def run(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Normalize text in each page; drop pages that become empty after cleaning."""
    result = []
    for page_num, text in pages:
        cleaned = _normalize(text)
        if cleaned:
            result.append((page_num, cleaned))
    return result
