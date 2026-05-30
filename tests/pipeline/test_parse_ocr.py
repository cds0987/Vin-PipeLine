"""
Tests for OCR fallback behaviour in pipeline.parsers._visual.

The visual parser has two OCR paths:
  1. Standalone images (.png/.jpg/…) → direct OCR via AIProvider.ocr()
  2. Mixed documents (.pdf/.docx/…) with no LLM client → text-only extraction

These tests verify the _parse_image path (standalone images), since
that is the publicly testable OCR integration point.
"""
from __future__ import annotations

import io


class _TrackingOCR:
    """OCR provider that records every call and returns configurable text."""

    def __init__(self, response: str = "ocr from rendered page") -> None:
        self.calls: list[bytes] = []
        self._response = response

    def ocr(self, image_bytes: bytes) -> str:
        self.calls.append(image_bytes)
        return self._response

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def caption(self, texts: list[str]) -> list[str]:
        return texts

    def get_llm_client(self):
        return None


def _make_png_bytes() -> bytes:
    """Create a minimal PNG image in memory."""
    from PIL import Image

    img = Image.new("RGB", (50, 50), "white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ─── _parse_image (standalone image → direct OCR) ─────────────────────────────

def test_parse_image_calls_ocr_with_raw_bytes():
    from pipeline.parsers import _visual

    raw = _make_png_bytes()
    provider = _TrackingOCR("some ocr text here")
    _visual.run(raw, ".png", provider)

    assert provider.calls == [raw]


def test_parse_image_returns_ocr_text():
    from pipeline.parsers import _visual

    provider = _TrackingOCR("policy content from OCR")
    result = _visual.run(_make_png_bytes(), ".png", provider)

    assert "policy content from OCR" in result


def test_parse_image_returns_empty_when_ocr_too_short():
    from pipeline.parsers import _visual

    provider = _TrackingOCR("short")  # < _MIN_OCR_CHARS threshold
    result = _visual.run(_make_png_bytes(), ".png", provider)

    assert result == ""


def test_parse_image_works_for_jpg():
    from pipeline.parsers import _visual

    from PIL import Image

    img = Image.new("RGB", (50, 50), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    provider = _TrackingOCR("jpeg ocr content here")

    result = _visual.run(buf.getvalue(), ".jpg", provider)

    assert provider.calls != []
    assert "jpeg ocr content" in result
