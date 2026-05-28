from __future__ import annotations

from config import settings
from adapters.file_adapter import FileAdapter
from pipeline.run import run


def test_pipeline_run_indexes_document(fake_ai_provider, vector_store, metadata_store, public_permission):
    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-pipeline")
    job.permission = public_permission

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
    stored_permission = metadata_store.get_permission("doc-pipeline")
    assert stored_permission is not None
    assert stored_permission.visibility == "public"
