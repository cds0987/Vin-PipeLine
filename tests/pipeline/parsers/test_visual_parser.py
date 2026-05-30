"""
Unit tests for pipeline.parsers._visual

All external dependencies (MarkItDown, OpenAI client) are fully mocked.
No real files, no network, no AI calls.

Covers:
  _parse_image   — standalone image OCR via ai_provider.ocr()
  _parse_mixed   — mixed documents: with llm_client and without (mock fallback)
  _convert_with_llm — MarkItDown + llm_client integration
  run()          — format dispatch
"""
from __future__ import annotations

import sys
import types

import pytest


# ── stubs ─────────────────────────────────────────────────────────────────────


class _MockAI:
    """AIProvider stub — no real LLM client."""
    def __init__(self, ocr_response: str = "ocr result") -> None:
        self._response = ocr_response
        self.ocr_calls: list[bytes] = []

    def ocr(self, image_bytes: bytes) -> str:
        self.ocr_calls.append(image_bytes)
        return self._response

    def embed(self, texts):
        return [[0.0] for _ in texts]

    def get_llm_client(self):
        return None   # mock mode — no real client


class _FakeLLMClient:
    """Minimal OpenAI-compatible client stub."""
    pass


class _AIWithClient:
    """AIProvider stub that has a real (fake) LLM client."""
    def __init__(self, ocr_response: str = "") -> None:
        self._response = ocr_response
        self._client = _FakeLLMClient()

    def ocr(self, image_bytes: bytes) -> str:
        return self._response

    def embed(self, texts):
        return [[0.0] for _ in texts]

    def get_llm_client(self):
        return self._client


def _patch_markitdown(monkeypatch, text: str) -> None:
    """Inject a MarkItDown stub that always returns `text`."""
    class _Result:
        text_content = text

    class _MD:
        def __init__(self, **_kwargs): pass
        def convert(self, path): return _Result()

    mod = types.ModuleType("markitdown")
    mod.MarkItDown = _MD
    monkeypatch.setitem(sys.modules, "markitdown", mod)


def _patch_text_extract(monkeypatch, returns: str = "") -> None:
    monkeypatch.setattr("pipeline.parsers._visual._text_extract", lambda *_: returns)


# ── _parse_image ──────────────────────────────────────────────────────────────


def test_image_returns_ocr_text():
    from pipeline.parsers import _visual
    ai = _MockAI("Sơ đồ kiến trúc hệ thống")
    assert _visual._parse_image(b"img", ai) == "Sơ đồ kiến trúc hệ thống"


def test_image_passes_exact_bytes_to_ocr():
    from pipeline.parsers import _visual
    ai = _MockAI("text")
    _visual._parse_image(b"raw_png_bytes", ai)
    assert ai.ocr_calls == [b"raw_png_bytes"]


def test_image_empty_ocr_returns_empty():
    from pipeline.parsers import _visual
    assert _visual._parse_image(b"img", _MockAI("")) == ""


def test_image_whitespace_ocr_returns_empty():
    from pipeline.parsers import _visual
    assert _visual._parse_image(b"img", _MockAI("   \n  ")) == ""


def test_image_below_min_chars_returns_empty():
    from pipeline.parsers import _visual
    # 9 chars < _MIN_OCR_CHARS (10) → discard as noise
    assert _visual._parse_image(b"img", _MockAI("123456789")) == ""


def test_image_exactly_min_chars_is_kept():
    from pipeline.parsers import _visual
    # exactly 10 chars → keep
    assert _visual._parse_image(b"img", _MockAI("1234567890")) == "1234567890"


# ── _parse_mixed: with llm_client ────────────────────────────────────────────


def test_mixed_with_llm_client_calls_markitdown(monkeypatch):
    convert_calls: list[str] = []

    class _Result:
        text_content = "# Báo cáo Q1\n\nDoanh thu tăng 18%"

    class _MD:
        def __init__(self, **kwargs):
            self._kwargs = kwargs
        def convert(self, path):
            convert_calls.append(path)
            return _Result()

    mod = types.ModuleType("markitdown")
    mod.MarkItDown = _MD
    monkeypatch.setitem(sys.modules, "markitdown", mod)

    from pipeline.parsers import _visual
    ai = _AIWithClient()
    result = _visual._parse_mixed(b"pdf bytes", ".pdf", ai)

    assert convert_calls, "MarkItDown.convert() was not called"
    assert "Báo cáo Q1" in result
    assert "18%" in result


def test_mixed_with_llm_client_strips_output(monkeypatch):
    _patch_markitdown(monkeypatch, "\n\n# Title\n\nContent\n\n")
    from pipeline.parsers import _visual
    result = _visual._parse_mixed(b"data", ".docx", _AIWithClient())
    assert result == "# Title\n\nContent"


def test_mixed_with_llm_client_returns_empty_when_markitdown_returns_none(monkeypatch):
    class _NullResult:
        text_content = None

    class _MD:
        def __init__(self, **_): pass
        def convert(self, _): return _NullResult()

    mod = types.ModuleType("markitdown")
    mod.MarkItDown = _MD
    monkeypatch.setitem(sys.modules, "markitdown", mod)

    from pipeline.parsers import _visual
    assert _visual._parse_mixed(b"data", ".pdf", _AIWithClient()) == ""


def test_mixed_llm_client_received_from_provider(monkeypatch):
    """MarkItDown must receive the exact client object from ai_provider."""
    received_clients: list = []

    class _MD:
        def __init__(self, llm_client=None, **_):
            received_clients.append(llm_client)
        def convert(self, _):
            class R: text_content = "ok"
            return R()

    mod = types.ModuleType("markitdown")
    mod.MarkItDown = _MD
    monkeypatch.setitem(sys.modules, "markitdown", mod)

    from pipeline.parsers import _visual
    ai = _AIWithClient()
    _visual._parse_mixed(b"data", ".pdf", ai)

    assert received_clients[0] is ai._client


# ── _parse_mixed: mock fallback (no llm_client) ───────────────────────────────


def test_mixed_without_llm_client_falls_back_to_text(monkeypatch):
    _patch_text_extract(monkeypatch, "text-only fallback content")
    from pipeline.parsers import _visual
    result = _visual._parse_mixed(b"data", ".pdf", _MockAI())
    assert result == "text-only fallback content"


def test_mixed_mock_does_not_call_markitdown(monkeypatch):
    markitdown_called = []
    _patch_markitdown(monkeypatch, "should not appear")
    monkeypatch.setattr(
        "pipeline.parsers._visual._convert_with_llm",
        lambda *_: markitdown_called.append(1) or "",
    )
    _patch_text_extract(monkeypatch, "fallback")

    from pipeline.parsers import _visual
    result = _visual._parse_mixed(b"data", ".xlsx", _MockAI())

    assert markitdown_called == []
    assert result == "fallback"


# ── _convert_with_llm: tempfile lifecycle ─────────────────────────────────────


def test_convert_with_llm_deletes_tempfile(monkeypatch):
    import os
    import tempfile as _tf

    _real = _tf.NamedTemporaryFile
    created: list[str] = []

    class _Spy:
        def __init__(self, suffix, delete):
            self._inner = _real(suffix=suffix, delete=delete)
            created.append(self._inner.name)
        def __enter__(self): return self._inner.__enter__()
        def __exit__(self, *a): return self._inner.__exit__(*a)
        def write(self, d): return self._inner.write(d)
        @property
        def name(self): return self._inner.name

    monkeypatch.setattr(_tf, "NamedTemporaryFile", _Spy)
    _patch_markitdown(monkeypatch, "result")

    from pipeline.parsers import _visual
    _visual._convert_with_llm(b"data", ".pdf", _FakeLLMClient())

    assert created and not os.path.exists(created[0])


def test_convert_with_llm_writes_correct_bytes(monkeypatch):
    import tempfile as _tf

    _real = _tf.NamedTemporaryFile
    written: list[bytes] = []

    class _Spy:
        def __init__(self, suffix, delete):
            self._inner = _real(suffix=suffix, delete=delete)
        def __enter__(self): return self._inner.__enter__()
        def __exit__(self, *a):
            self._inner.flush()
            self._inner.seek(0)
            written.append(self._inner.read())
            return self._inner.__exit__(*a)
        def write(self, d): return self._inner.write(d)
        @property
        def name(self): return self._inner.name

    monkeypatch.setattr(_tf, "NamedTemporaryFile", _Spy)
    _patch_markitdown(monkeypatch, "result")

    from pipeline.parsers import _visual
    payload = b"VSF internal document \xc3\xa0\xc3\xa1"
    _visual._convert_with_llm(payload, ".docx", _FakeLLMClient())

    assert written[0] == payload


# ── run() dispatch ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("suffix", [
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff",
])
def test_run_image_suffixes_call_parse_image(monkeypatch, suffix):
    called = []
    monkeypatch.setattr(
        "pipeline.parsers._visual._parse_image",
        lambda fb, ai: called.append(suffix) or "img result",
    )
    from pipeline.parsers import _visual
    result = _visual.run(b"img", suffix, _MockAI())
    assert called == [suffix]
    assert result == "img result"


@pytest.mark.parametrize("suffix", [
    ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".odp", ".ods", ".rtf",
])
def test_run_mixed_suffixes_call_parse_mixed(monkeypatch, suffix):
    called = []
    monkeypatch.setattr(
        "pipeline.parsers._visual._parse_mixed",
        lambda fb, sfx, ai: called.append(sfx) or "mixed result",
    )
    from pipeline.parsers import _visual
    result = _visual.run(b"doc", suffix, _MockAI())
    assert called == [suffix]
    assert result == "mixed result"


def test_run_unknown_suffix_falls_back_to_text(monkeypatch):
    _patch_text_extract(monkeypatch, "text fallback")
    from pipeline.parsers import _visual
    result = _visual.run(b"data", ".xyz", _MockAI())
    assert result == "text fallback"


def test_run_normalises_uppercase_suffix(monkeypatch):
    called = []
    monkeypatch.setattr(
        "pipeline.parsers._visual._parse_image",
        lambda fb, ai: called.append(True) or "ok",
    )
    from pipeline.parsers import _visual
    _visual.run(b"img", ".PNG", _MockAI())
    assert called == [True]
