from __future__ import annotations

import re


def _normalize(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
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
