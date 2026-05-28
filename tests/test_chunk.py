from __future__ import annotations

import importlib

from models.ingest_job import IngestJob

chunk_module = importlib.import_module("pipeline.03_chunk")


def test_chunk_sliding_window(monkeypatch):
    monkeypatch.setattr("config.settings.CHUNK_SIZE", 6)
    monkeypatch.setattr("config.settings.CHUNK_OVERLAP", 2)
    text = "one two three four five six seven eight nine ten eleven"
    job = IngestJob(doc_id="doc-1", file_uri="data/sample/policy.txt")

    chunks = chunk_module.run(text, job)

    assert [chunk.chunk_id for chunk in chunks] == [
        "doc-1_chunk_0000",
        "doc-1_chunk_0001",
        "doc-1_chunk_0002",
    ]
    assert chunks[0].content == "one two three four five six"
    assert chunks[1].content.startswith("five six seven eight")
    assert chunks[0].metadata["chunk_strategy"] == "sliding_window"
