from __future__ import annotations

import importlib

from app.domain.documents.models import MarkdownDocument
from models.ingest_job import IngestJob

chunk_module = importlib.import_module("pipeline.03_chunk")


def test_split_by_heading_creates_multiple_sections():
    markdown = MarkdownDocument(
        doc_id="doc-1",
        source_uri="data/sample/policy.txt",
        markdown_content="# Policy\nIntro\n\n## Travel\nTravel body\n\n## Leave\nLeave body",
    )
    job = IngestJob(doc_id="doc-1", file_uri="data/sample/policy.txt")

    sections = chunk_module.run(markdown, job)

    assert [section.section_id for section in sections] == [
        "doc-1_section_0000",
        "doc-1_section_0001",
        "doc-1_section_0002",
    ]
    assert sections[0].section_content.startswith("# Policy")
    assert sections[1].heading_path == ["Policy", "Travel"]
    assert sections[2].heading_path == ["Policy", "Leave"]


def test_split_populates_heading_leaf():
    markdown = MarkdownDocument(
        doc_id="doc-h",
        source_uri="data/sample/policy.txt",
        markdown_content="# Top\nText\n\n## Sub\nMore text",
    )
    job = IngestJob(doc_id="doc-h", file_uri="data/sample/policy.txt")

    sections = chunk_module.run(markdown, job)

    # heading must be the leaf (last element of heading_path)
    assert sections[0].heading == "Top"
    assert sections[1].heading == "Sub"


def test_split_populates_section_order():
    markdown = MarkdownDocument(
        doc_id="doc-ord",
        source_uri="data/sample/policy.txt",
        markdown_content="# A\nBody A\n\n# B\nBody B\n\n# C\nBody C",
    )
    job = IngestJob(doc_id="doc-ord", file_uri="data/sample/policy.txt")

    sections = chunk_module.run(markdown, job)

    assert [s.section_order for s in sections] == [0, 1, 2]


def test_split_without_headings_returns_single_section():
    # Content with no headings → _split_markdown collects everything into one
    # section (heading_path=[]), so the document is preserved intact.
    markdown = MarkdownDocument(
        doc_id="doc-2",
        source_uri="data/sample/policy.txt",
        markdown_content="paragraph one\n\nparagraph two\n\nparagraph three",
    )
    job = IngestJob(doc_id="doc-2", file_uri="data/sample/policy.txt")

    sections = chunk_module.run(markdown, job)

    assert len(sections) == 1
    assert sections[0].heading_path == []
    assert "paragraph one" in sections[0].section_content
    assert "paragraph three" in sections[0].section_content


def test_split_empty_markdown_returns_empty():
    markdown = MarkdownDocument(
        doc_id="doc-3",
        source_uri="data/sample/policy.txt",
        markdown_content="",
    )
    job = IngestJob(doc_id="doc-3", file_uri="data/sample/policy.txt")
    sections = chunk_module.run(markdown, job)
    assert sections == []
