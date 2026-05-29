from __future__ import annotations

import pytest

from config import settings
from adapters.file_adapter import FileAdapter
from pipeline.run import run


def test_pipeline_run_indexes_document(fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-pipeline")

    result = run(
        job,
        ai_provider=fake_ai_provider,
        vector_store=vector_store,
        metadata_store=metadata_store,
    )

    assert result["doc_id"] == "doc-pipeline"
    assert result["status"] == "indexed"
    assert result["chunk_count"] >= 1
    assert result["embedding_model"] == settings.EMBED_MODEL

    stored_chunks = vector_store.search([29.0, 1.0, 0.5], top_k=5)
    assert stored_chunks

    # s3_uri stamped in Qdrant payload
    assert stored_chunks[0].metadata.get("s3_uri") == "data/sample/policy.txt"

    # document indexed in metadata store
    doc = metadata_store.get_document("doc-pipeline")
    assert doc is not None
    assert doc.status == "indexed"


def test_pipeline_run_times_out_before_work(monkeypatch, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-timeout")

    with pytest.raises(TimeoutError):
        run(
            job,
            ai_provider=fake_ai_provider,
            vector_store=vector_store,
            metadata_store=metadata_store,
            deadline_monotonic=0.0,
        )

    doc = metadata_store.get_document("doc-timeout")
    assert doc is not None
    assert doc.status == "failed"
