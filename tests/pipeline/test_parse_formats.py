"""
Runtime parse wrapper tests.

Purpose preserved:
  - supported text formats parse successfully
  - image formats route through OCR-capable path
  - HTML becomes readable text/markdown
  - unknown extension still falls back gracefully
  - runtime wrapper returns a single markdown page tuple
"""
from __future__ import annotations

import importlib

from models.ingest_job import IngestJob

parse = importlib.import_module("pipeline.01_parse")


class _MockOCRProvider:
    def embed(self, texts): return [[0.0] for _ in texts]
    def caption(self, texts): return texts
    def ocr(self, image_bytes: bytes) -> str: return f"ocr:{image_bytes.decode(errors='replace')}"
    def get_llm_client(self): return None


def test_parse_txt_returns_single_markdown_page():
    job = IngestJob(doc_id="d1", file_uri="doc.txt")
    assert parse.run(job, _MockOCRProvider(), b"plain text document") == [(1, "plain text document")]


def test_parse_md_returns_single_markdown_page():
    job = IngestJob(doc_id="d2", file_uri="readme.md")
    result = parse.run(job, _MockOCRProvider(), b"# heading\ncontent")
    assert result == [(1, "# heading\ncontent")]


def test_parse_html_returns_readable_text():
    job = IngestJob(doc_id="d3", file_uri="page.html")
    result = parse.run(job, _MockOCRProvider(), b"<p>html content</p>")
    assert result == [(1, "html content")]


def test_parse_htm_returns_readable_text():
    job = IngestJob(doc_id="d4", file_uri="page.htm")
    result = parse.run(job, _MockOCRProvider(), b"<p>htm content</p>")
    assert result == [(1, "htm content")]


def test_parse_unknown_extension_falls_back_to_text():
    job = IngestJob(doc_id="d5", file_uri="data.xyz")
    assert parse.run(job, _MockOCRProvider(), b"unknown but readable") == [(1, "unknown but readable")]


def test_parse_image_routes_through_ocr():
    job = IngestJob(doc_id="d6", file_uri="scan.png")
    assert parse.run(job, _MockOCRProvider(), b"img_data") == [(1, "ocr:img_data")]


def test_parse_blank_text_returns_empty():
    job = IngestJob(doc_id="d7", file_uri="blank.txt")
    assert parse.run(job, _MockOCRProvider(), b"   \n\t  ") == []


def test_parse_wrapper_always_returns_page_number_one():
    job = IngestJob(doc_id="d8", file_uri="page.html")
    result = parse.run(job, _MockOCRProvider(), b"<p>text</p>")
    assert result[0][0] == 1
