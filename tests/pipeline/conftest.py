"""
Pipeline-specific fixtures.

Provides ready-made file bytes and IngestJob objects for each supported format
so individual pipeline tests don't need to know about data/sample/ paths or
IngestJob field defaults.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tests.factories import make_ingest_job

_SAMPLE = Path("data/sample")


@pytest.fixture
def txt_bytes() -> bytes:
    return (_SAMPLE / "policy.txt").read_bytes()


@pytest.fixture
def md_bytes() -> bytes:
    return (_SAMPLE / "faq.md").read_bytes()


@pytest.fixture
def html_bytes() -> bytes:
    return (_SAMPLE / "handbook.html").read_bytes()


@pytest.fixture
def txt_job(txt_bytes, tmp_path) -> tuple:
    """Returns (job, file_bytes) for a .txt document."""
    f = tmp_path / "policy.txt"
    f.write_bytes(txt_bytes)
    return make_ingest_job(file_uri=str(f), file_name="policy.txt"), txt_bytes


@pytest.fixture
def md_job(md_bytes, tmp_path) -> tuple:
    f = tmp_path / "faq.md"
    f.write_bytes(md_bytes)
    return make_ingest_job(file_uri=str(f), file_name="faq.md"), md_bytes


@pytest.fixture
def html_job(html_bytes, tmp_path) -> tuple:
    f = tmp_path / "handbook.html"
    f.write_bytes(html_bytes)
    return make_ingest_job(file_uri=str(f), file_name="handbook.html"), html_bytes


@pytest.fixture
def minimal_pages() -> list[tuple[int, str]]:
    """Smallest valid pages list: one page with real content."""
    return [(1, "This is a test document with enough content to chunk and embed.")]


@pytest.fixture
def multi_page_pages() -> list[tuple[int, str]]:
    return [
        (1, "Page one content. " * 20),
        (2, "Page two content. " * 20),
        (3, "Page three content. " * 20),
    ]
