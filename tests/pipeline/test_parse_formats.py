"""
Extended parse tests — covers formats and edge cases NOT in the existing test_parse.py:
  _parse_text, _parse_html, _parse_image, _parse_docx (mocked),
  _parse_pdf extra cases (text layer, multi-page, all-empty),
  run() dispatch for each extension including unknown → text fallback.
"""
from __future__ import annotations

import importlib
import sys
import types

parse = importlib.import_module("pipeline.01_parse")


class _MockOCRProvider:
    def embed(self, texts):
        return [[0.0] for _ in texts]

    def ocr(self, image_bytes: bytes) -> str:
        return f"ocr:{image_bytes.decode(errors='replace')}"


# ─── _parse_text ──────────────────────────────────────────────────────────────

def test_parse_text_returns_single_page():
    assert parse._parse_text(b"hello world") == [(1, "hello world")]


def test_parse_text_whitespace_only_returns_empty():
    assert parse._parse_text(b"   ") == []


def test_parse_text_empty_bytes_returns_empty():
    assert parse._parse_text(b"") == []


def test_parse_text_decodes_utf8():
    assert parse._parse_text("xin chào".encode("utf-8")) == [(1, "xin chào")]


def test_parse_text_ignores_undecodable_bytes():
    result = parse._parse_text(b"ok \xff byte")
    assert result  # gracefully decoded, not raised


# ─── _parse_html ──────────────────────────────────────────────────────────────

def test_parse_html_strips_tags():
    assert parse._parse_html(b"<p>Hello <b>World</b></p>") == [(1, "Hello\nWorld")]


def test_parse_html_ignores_whitespace_only_nodes():
    assert parse._parse_html(b"<div>   </div><p>real</p>") == [(1, "real")]


def test_parse_html_empty_document_returns_empty():
    assert parse._parse_html(b"<html></html>") == []


def test_parse_html_joins_text_from_multiple_elements():
    result = parse._parse_html(b"<p>Line A</p><p>Line B</p>")
    assert len(result) == 1
    assert "Line A" in result[0][1]
    assert "Line B" in result[0][1]


def test_parse_html_page_number_is_always_one():
    result = parse._parse_html(b"<p>text</p>")
    assert result[0][0] == 1


# ─── _parse_image ─────────────────────────────────────────────────────────────

def test_parse_image_calls_ocr_with_raw_bytes():
    provider = _MockOCRProvider()
    result = parse._parse_image(b"img_data", provider)
    assert result == [(1, "ocr:img_data")]


def test_parse_image_empty_ocr_result_returns_empty():
    class _BlankOCR:
        def ocr(self, _): return "   "
        def embed(self, t): return []

    assert parse._parse_image(b"anything", _BlankOCR()) == []


def test_parse_image_page_number_is_always_one():
    result = parse._parse_image(b"x", _MockOCRProvider())
    assert result[0][0] == 1


# ─── _parse_docx (mocked) ─────────────────────────────────────────────────────

def test_parse_docx_extracts_paragraphs(monkeypatch):
    fake_doc = types.SimpleNamespace(
        paragraphs=[types.SimpleNamespace(text="first paragraph"),
                    types.SimpleNamespace(text="second paragraph")]
    )
    monkeypatch.setitem(sys.modules, "docx",
                        types.SimpleNamespace(Document=lambda _stream: fake_doc))
    result = parse._parse_docx(b"bytes")
    assert result == [(1, "first paragraph\nsecond paragraph")]


def test_parse_docx_skips_blank_paragraphs(monkeypatch):
    fake_doc = types.SimpleNamespace(
        paragraphs=[
            types.SimpleNamespace(text="real"),
            types.SimpleNamespace(text=""),
            types.SimpleNamespace(text="   "),
            types.SimpleNamespace(text="also real"),
        ]
    )
    monkeypatch.setitem(sys.modules, "docx",
                        types.SimpleNamespace(Document=lambda _stream: fake_doc))
    result = parse._parse_docx(b"bytes")
    assert len(result) == 1
    assert "real" in result[0][1]
    assert "also real" in result[0][1]


def test_parse_docx_all_blank_returns_empty(monkeypatch):
    fake_doc = types.SimpleNamespace(
        paragraphs=[types.SimpleNamespace(text=""), types.SimpleNamespace(text="  ")]
    )
    monkeypatch.setitem(sys.modules, "docx",
                        types.SimpleNamespace(Document=lambda _stream: fake_doc))
    assert parse._parse_docx(b"bytes") == []


# ─── _parse_pdf — extra cases beyond the existing rendered-OCR test ───────────

def test_parse_pdf_uses_text_layer_and_does_not_call_ocr(monkeypatch):
    """PDF page with text → OCR provider must never be invoked."""
    class _TextPage:
        images = []
        def extract_text(self): return "pdf text content"

    class _TextReader:
        def __init__(self, *_a, **_kw): self.pages = [_TextPage()]

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_TextReader))
    monkeypatch.setitem(sys.modules, "fitz", types.SimpleNamespace(
        Matrix=lambda *_: object(),
        open=lambda **_: types.SimpleNamespace(
            load_page=lambda _i: types.SimpleNamespace(
                get_pixmap=lambda **_: types.SimpleNamespace(tobytes=lambda _: b"")
            ),
            close=lambda: None,
        ),
    ))

    class _FailOnOCR:
        def ocr(self, _): raise AssertionError("OCR must not be called for text-based PDF")
        def embed(self, t): return []

    result = parse._parse_pdf(b"%PDF", _FailOnOCR())
    assert result == [(1, "pdf text content")]


def test_parse_pdf_returns_all_pages(monkeypatch):
    class _Page:
        images = []
        def __init__(self, t): self._t = t
        def extract_text(self): return self._t

    class _Reader:
        def __init__(self, *_a, **_kw):
            self.pages = [_Page("p1"), _Page("p2"), _Page("p3")]

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_Reader))
    monkeypatch.setitem(sys.modules, "fitz", None)

    result = parse._parse_pdf(b"%PDF", _MockOCRProvider())
    assert len(result) == 3
    assert result[0] == (1, "p1")
    assert result[2] == (3, "p3")


def test_parse_pdf_all_empty_pages_returns_empty(monkeypatch):
    class _EmptyPage:
        images = []
        def extract_text(self): return ""

    class _EmptyReader:
        def __init__(self, *_a, **_kw): self.pages = [_EmptyPage(), _EmptyPage()]

    monkeypatch.setitem(sys.modules, "pypdf", types.SimpleNamespace(PdfReader=_EmptyReader))
    monkeypatch.setitem(sys.modules, "fitz", types.SimpleNamespace(
        Matrix=lambda *_: object(),
        open=lambda **_: types.SimpleNamespace(
            load_page=lambda _i: types.SimpleNamespace(
                get_pixmap=lambda **_: types.SimpleNamespace(tobytes=lambda _: b"")
            ),
            close=lambda: None,
        ),
    ))

    class _EmptyOCR:
        def ocr(self, _): return ""
        def embed(self, t): return []

    assert parse._parse_pdf(b"%PDF", _EmptyOCR()) == []


# ─── run() extension dispatch ─────────────────────────────────────────────────

def test_run_dispatches_txt_file():
    from models.ingest_job import IngestJob
    job = IngestJob(doc_id="d1", file_uri="doc.txt")
    assert parse.run(job, _MockOCRProvider(), b"plain text document") == [(1, "plain text document")]


def test_run_dispatches_md_file():
    from models.ingest_job import IngestJob
    job = IngestJob(doc_id="d2", file_uri="readme.md")
    result = parse.run(job, _MockOCRProvider(), b"# heading\ncontent")
    assert result == [(1, "# heading\ncontent")]


def test_run_dispatches_html_file():
    from models.ingest_job import IngestJob
    job = IngestJob(doc_id="d3", file_uri="page.html")
    assert parse.run(job, _MockOCRProvider(), b"<p>html content</p>") == [(1, "html content")]


def test_run_dispatches_htm_file():
    from models.ingest_job import IngestJob
    job = IngestJob(doc_id="d4", file_uri="page.htm")
    assert parse.run(job, _MockOCRProvider(), b"<p>htm content</p>") == [(1, "htm content")]


def test_run_unknown_extension_falls_back_to_text():
    from models.ingest_job import IngestJob
    job = IngestJob(doc_id="d5", file_uri="data.xyz")
    assert parse.run(job, _MockOCRProvider(), b"unknown but readable") == [(1, "unknown but readable")]
