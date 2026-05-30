"""
Unit tests for pipeline.parsers (public router / __init__.py)

Verifies routing logic: which parser is called for each format,
when ai_provider is required, and suffix normalisation.
"""
from __future__ import annotations

import pytest


# ── stubs ─────────────────────────────────────────────────────────────────────


class _AI:
    def ocr(self, _): return "ocr"
    def embed(self, t): return [[0.0] for _ in t]
    def get_llm_client(self): return None


# ── always-visual formats ─────────────────────────────────────────────────────


@pytest.mark.parametrize("suffix", [
    # standalone images
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff",
    # mixed-content documents
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".odt", ".odp", ".ods", ".rtf",
])
def test_visual_formats_route_to_visual_parser(monkeypatch, suffix):
    called = []

    monkeypatch.setattr(
        "pipeline.parsers._visual.run",
        lambda fb, sfx, ai: called.append(sfx) or "visual result",
    )

    from pipeline import parsers
    result = parsers.run(b"data", suffix, ai_provider=_AI())

    assert called == [suffix]
    assert result == "visual result"


@pytest.mark.parametrize("suffix", [
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff",
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".odt", ".odp", ".ods", ".rtf",
])
def test_visual_formats_raise_without_ai_provider(suffix):
    from pipeline import parsers
    with pytest.raises(ValueError, match="ai_provider"):
        parsers.run(b"data", suffix, ai_provider=None)


# ── text-only formats ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("suffix", [
    ".txt", ".md", ".html", ".htm", ".ipynb",
    ".py", ".js", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".csv", ".xml",
])
def test_text_formats_route_to_text_parser(monkeypatch, suffix):
    called = []

    monkeypatch.setattr(
        "pipeline.parsers._text.run",
        lambda fb, sfx: called.append(sfx) or "text result",
    )

    from pipeline import parsers
    result = parsers.run(b"data", suffix)

    assert called == [suffix]
    assert result == "text result"


@pytest.mark.parametrize("suffix", [
    ".txt", ".md", ".html", ".htm", ".ipynb",
    ".py", ".js", ".ts", ".tsx",
    ".json", ".yaml", ".yml", ".csv",
])
def test_text_formats_do_not_need_ai_provider(monkeypatch, suffix):
    monkeypatch.setattr("pipeline.parsers._text.run", lambda fb, sfx: "ok")
    from pipeline import parsers
    assert parsers.run(b"data", suffix) == "ok"


# ── suffix normalisation ──────────────────────────────────────────────────────


@pytest.mark.parametrize("suffix,expected", [
    (".TXT", ".txt"),
    (".PDF", ".pdf"),
    (".DOCX", ".docx"),
    (".PNG", ".png"),
    (".PPTX", ".pptx"),
    (".Xlsx", ".xlsx"),
    (".MD", ".md"),
])
def test_uppercase_suffix_normalised_before_routing(monkeypatch, suffix, expected):
    routed_to_visual: list[str] = []
    routed_to_text: list[str] = []

    monkeypatch.setattr(
        "pipeline.parsers._visual.run",
        lambda fb, sfx, ai: routed_to_visual.append(sfx) or "v",
    )
    monkeypatch.setattr(
        "pipeline.parsers._text.run",
        lambda fb, sfx: routed_to_text.append(sfx) or "t",
    )

    from pipeline import parsers
    parsers.run(b"data", suffix, ai_provider=_AI())

    all_routed = routed_to_visual + routed_to_text
    assert all_routed == [expected], f"expected routing with '{expected}', got {all_routed}"


# ── unknown format falls through to text ─────────────────────────────────────


def test_unknown_suffix_routed_to_text(monkeypatch):
    called = []
    monkeypatch.setattr(
        "pipeline.parsers._text.run",
        lambda fb, sfx: called.append(sfx) or "text",
    )
    from pipeline import parsers
    result = parsers.run(b"data", ".xyz")
    assert called == [".xyz"]
    assert result == "text"
