from __future__ import annotations

import importlib

from models.ingest_job import IngestJob

chunk_module = importlib.import_module("pipeline.03_chunk")


def test_chunk_sliding_window(monkeypatch):
    monkeypatch.setattr("config.settings.CHUNK_SIZE", 6)
    monkeypatch.setattr("config.settings.CHUNK_OVERLAP", 2)
    pages = [(1, "one two three four five six seven eight nine ten eleven")]
    job = IngestJob(doc_id="doc-1", file_uri="data/sample/policy.txt")

    chunks = chunk_module.run(pages, job)

    assert [chunk.chunk_id for chunk in chunks] == [
        "doc-1_chunk_0000",
        "doc-1_chunk_0001",
        "doc-1_chunk_0002",
    ]
    assert chunks[0].content == "one two three four five six"
    assert chunks[1].content.startswith("five six seven eight")
    assert chunks[0].metadata["chunk_strategy"] == "sliding_window"


def test_chunk_page_tracking(monkeypatch):
    monkeypatch.setattr("config.settings.CHUNK_SIZE", 10)
    monkeypatch.setattr("config.settings.CHUNK_OVERLAP", 0)
    pages = [
        (1, "page one content here"),
        (2, "page two content here"),
    ]
    job = IngestJob(doc_id="doc-2", file_uri="data/sample/policy.txt")

    chunks = chunk_module.run(pages, job)

    assert chunks
    # All chunks must have page_start and page_end populated (not None)
    for chunk in chunks:
        assert chunk.page_start is not None
        assert chunk.page_end is not None
    # First chunk should start at page 1
    assert chunks[0].page_start == 1


def test_chunk_empty_pages_returns_empty():
    job = IngestJob(doc_id="doc-3", file_uri="data/sample/policy.txt")
    chunks = chunk_module.run([], job)
    assert chunks == []
