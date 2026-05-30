from __future__ import annotations

import re

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _normalize(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = _CONTROL_CHARS_RE.sub("", normalized)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def run(pages: list[tuple[int, str]] | str) -> list[tuple[int, str]] | str:
    """Normalize text while keeping backward compatibility.

    - ``list[tuple[int, str]]`` in legacy page-based flow
    - ``str`` in newer Markdown-first flow
    """
    if isinstance(pages, str):
        return _normalize(pages)

    result = []
    for page_num, text in pages:
        cleaned = _normalize(text)
        if cleaned:
            result.append((page_num, cleaned))
    return result
