from __future__ import annotations

from adapters.file_adapter import FileAdapter
from models.ingest_job import IngestJob
from pipeline.run import run


def test_health_endpoint(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "vector_store" in body
    assert "ai_provider" in body
    assert "scanner" in body


def test_search_endpoint_returns_results(api_client, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-api")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    response = api_client.post("/search", json={"query": "travel reimbursement", "top_k": 3})

    assert response.status_code == 200
    body = response.json()
    assert "results" in body
    assert "request_id" in body
    assert body["results"]
    first = body["results"][0]
    assert "chunk_id" in first
    assert "content" in first
    assert "score" in first
    assert "s3_uri" in first


def test_search_returns_s3_uri(api_client, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-s3uri")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    response = api_client.post("/search", json={"query": "policy"})

    assert response.status_code == 200
    results = response.json()["results"]
    assert results
    assert results[0]["s3_uri"] == "data/sample/policy.txt"


def test_status_endpoint_returns_document(api_client, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-status")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    response = api_client.get("/status/doc-status")

    assert response.status_code == 200
    body = response.json()
    assert body["doc_id"] == "doc-status"
    assert body["status"] == "indexed"


def test_scan_endpoint_returns_queued_count(api_client, monkeypatch):
    class FakeScanner:
        def __init__(self, _metadata_store) -> None:
            pass

        def scan(self, bucket=None, prefix=None):
            assert bucket == "bucket-a"
            assert prefix == "prefix-a"
            return [
                IngestJob(doc_id="doc-1", file_uri="s3://bucket-a/prefix-a/file-1.pdf"),
                IngestJob(doc_id="doc-2", file_uri="s3://bucket-a/prefix-a/file-2.pdf"),
            ]

    import api.main as api_main

    def fake_run_jobs(jobs, *_args):
        assert len(jobs) == 2
        return len(jobs)

    monkeypatch.setattr("adapters.s3_adapter.S3Scanner", FakeScanner)
    monkeypatch.setattr(api_main, "_run_jobs", fake_run_jobs)

    response = api_client.post("/scan", json={"bucket": "bucket-a", "prefix": "prefix-a"})

    assert response.status_code == 200
    assert response.json() == {"status": "scan started", "queued": 2}
