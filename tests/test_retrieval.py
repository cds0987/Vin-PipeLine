from __future__ import annotations

from adapters.file_adapter import FileAdapter
from pipeline.run import run
from retrieval.service import RetrievalService


def _index(doc_id, file_uri, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map(file_uri, doc_id=doc_id)
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)


def test_search_returns_chunks(fake_ai_provider, vector_store, metadata_store):
    _index("doc-a", "data/sample/policy.txt", fake_ai_provider, vector_store, metadata_store)
    service = RetrievalService(fake_ai_provider, vector_store)

    results = service.search("travel reimbursement", top_k=3)

    assert results
    assert results[0]["doc_id"] == "doc-a"


def test_search_includes_s3_uri(fake_ai_provider, vector_store, metadata_store):
    _index("doc-b", "data/sample/policy.txt", fake_ai_provider, vector_store, metadata_store)
    service = RetrievalService(fake_ai_provider, vector_store)

    results = service.search("policy", top_k=3)

    assert results
    assert results[0]["s3_uri"] == "data/sample/policy.txt"


def test_search_multiple_docs_returns_all(fake_ai_provider, vector_store, metadata_store):
    _index("doc-c", "data/sample/policy.txt", fake_ai_provider, vector_store, metadata_store)
    _index("doc-d", "data/sample/faq.md", fake_ai_provider, vector_store, metadata_store)
    service = RetrievalService(fake_ai_provider, vector_store)

    results = service.search("question", top_k=5)

    assert results
    doc_ids = {r["doc_id"] for r in results}
    assert len(doc_ids) >= 1
