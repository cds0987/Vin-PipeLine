"""
pipeline.parsers — unified document-to-Markdown conversion.

Public API (single entry point):

    from pipeline.parsers import run

    markdown = run(file_bytes, suffix)               # pure-text formats
    markdown = run(file_bytes, suffix, ai_provider)  # mixed / visual formats

Routing rules
─────────────
Each suffix maps to either ``_visual`` or ``_text`` strategy via the
``_PARSER_REGISTRY``. Adding a new format requires only a new entry in the
registry — the orchestration (``RunIngestJob``) does not need to change.

Strategy families:
  visual — formats that contain images, diagrams, or non-extractable text;
           require an ai_provider for OCR / captioning.
  text   — plain markup/code/data formats; no ai_provider needed.

Extending
─────────
New visual format: add ``".ext": "visual"`` to ``_PARSER_REGISTRY``.
New text format:   add ``".ext": "text"``   to ``_PARSER_REGISTRY``.
Unknown suffix:    falls back to text strategy (MarkItDown handles many types).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pipeline.parsers import _text, _visual

if TYPE_CHECKING:
    from utils.ai_provider import AIProvider

_Strategy = Literal["visual", "text"]

# Registry: suffix → strategy family.
# Only one place to update when adding a new document format.
_PARSER_REGISTRY: dict[str, _Strategy] = {
    # ── Standalone images ────────────────────────────────────────────────────
    ".png": "visual",
    ".jpg": "visual",
    ".jpeg": "visual",
    ".webp": "visual",
    ".bmp": "visual",
    ".tiff": "visual",
    # ── Office / mixed documents ─────────────────────────────────────────────
    ".pdf": "visual",
    ".docx": "visual",
    ".xlsx": "visual",
    ".pptx": "visual",
    ".odt": "visual",
    ".odp": "visual",
    ".ods": "visual",
    ".rtf": "visual",
    # ── Plain text / markup ──────────────────────────────────────────────────
    ".txt": "text",
    ".md": "text",
    ".html": "text",
    ".htm": "text",
    # ── Notebooks / code ─────────────────────────────────────────────────────
    ".ipynb": "text",
    ".py": "text",
    ".js": "text",
    ".ts": "text",
    ".tsx": "text",
    # ── Data ─────────────────────────────────────────────────────────────────
    ".json": "text",
    ".yaml": "text",
    ".yml": "text",
    ".csv": "text",
    ".xml": "text",
}


def run(
    file_bytes: bytes,
    suffix: str,
    ai_provider: AIProvider | None = None,
) -> str:
    """Parse any supported file into a Markdown string.

    Args:
        file_bytes: raw bytes of the document.
        suffix: file extension with dot, e.g. ``".pdf"``, ``".txt"``.
        ai_provider: required for all ``"visual"`` suffixes in the registry.

    Returns:
        Markdown string. Empty string if the document is blank.

    Raises:
        ValueError: if ai_provider is None for a visual-strategy suffix.
    """
    strategy = _PARSER_REGISTRY.get(suffix.lower(), "text")

    if strategy == "visual":
        return _visual.run(file_bytes, suffix.lower(), _require(ai_provider, suffix))

    return _text.run(file_bytes, suffix.lower())


# ── internal ──────────────────────────────────────────────────────────────────


def _require(provider: AIProvider | None, suffix: str) -> AIProvider:
    if provider is None:
        raise ValueError(
            f"ai_provider is required for '{suffix}' files. "
            "Pass an AIProvider instance or use a text-based format."
        )
    return provider
