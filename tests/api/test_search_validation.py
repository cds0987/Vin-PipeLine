"""
API edge-case tests — covers gaps not in existing test_api.py:
  - /search top_k boundary validation (< 1 and > 50 → 422)
  - /search with empty vector store returns empty results list
  - /search response always has request_id
  - /search with score_threshold=0.0 does not filter any result
  - /status response includes uploaded_at timestamp
  - /scan returns queued=0 when no new files
"""
from __future__ import annotations

import pytest


# ─── /search — top_k validation ───────────────────────────────────────────────

def test_search_top_k_zero_returns_422(api_client):
    assert api_client.post("/search", json={"query": "q", "top_k": 0}).status_code == 422


def test_search_top_k_negative_returns_422(api_client):
    assert api_client.post("/search", json={"query": "q", "top_k": -5}).status_code == 422


def test_search_top_k_51_returns_422(api_client):
    assert api_client.post("/search", json={"query": "q", "top_k": 51}).status_code == 422


def test_search_top_k_1_is_valid(api_client):
    assert api_client.post("/search", json={"query": "q", "top_k": 1}).status_code == 200


def test_search_top_k_50_is_valid(api_client):
    assert api_client.post("/search", json={"query": "q", "top_k": 50}).status_code == 200


def test_search_missing_query_field_returns_422(api_client):
    assert api_client.post("/search", json={"top_k": 5}).status_code == 422


def test_search_blank_query_returns_422(api_client):
    assert api_client.post("/search", json={"query": "   ", "top_k": 5}).status_code == 422


# ─── /search — empty store ────────────────────────────────────────────────────

def test_search_empty_store_returns_empty_results_list(api_client):
    body = api_client.post("/search", json={"query": "anything"}).json()
    assert body["results"] == []


def test_search_response_always_has_request_id(api_client):
    body = api_client.post("/search", json={"query": "x"}).json()
    assert "request_id" in body
    assert isinstance(body["request_id"], str)
    assert len(body["request_id"]) > 0


# ─── /search — score threshold = 0.0 passes everything through ───────────────

def test_search_threshold_zero_does_not_filter(monkeypatch, fake_ai_provider, vector_store, metadata_store):
    from adapters.file_adapter import FileAdapter
    from pipeline.run import run
    import api.main as api_main
    from retrieval.service import RetrievalService
    from fastapi.testclient import TestClient

    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr(api_main, "build_ai_provider", lambda: fake_ai_provider)
    monkeypatch.setattr(api_main, "build_vector_store", lambda: vector_store)
    monkeypatch.setattr(api_main, "build_metadata_store", lambda: metadata_store)

    with TestClient(api_main.app) as client:
        job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-threshold-zero")
        run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

        # With threshold=0.0 every chunk should pass the filter
        body = client.post("/search", json={"query": "policy", "top_k": 50}).json()
        assert body["results"]  # at least one result must come through


# ─── /status — field completeness ────────────────────────────────────────────

def test_status_response_includes_uploaded_at(api_client, fake_ai_provider, vector_store, metadata_store):
    from adapters.file_adapter import FileAdapter
    from pipeline.run import run

    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-fields")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    body = api_client.get("/status/doc-fields").json()
    assert "uploaded_at" in body
    assert body["uploaded_at"] is not None


def test_status_response_includes_total_chunks(api_client, fake_ai_provider, vector_store, metadata_store):
    from adapters.file_adapter import FileAdapter
    from pipeline.run import run

    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-chunks")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    body = api_client.get("/status/doc-chunks").json()
    assert "total_chunks" in body


def test_status_response_includes_file_type(api_client, fake_ai_provider, vector_store, metadata_store):
    from adapters.file_adapter import FileAdapter
    from pipeline.run import run

    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-ftype")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    body = api_client.get("/status/doc-ftype").json()
    assert "file_type" in body
    assert body["file_type"] == "txt"


# ─── /scan — queued=0 when scanner finds no files ─────────────────────────────

def test_scan_returns_zero_queued_when_no_new_files(api_client, monkeypatch):
    import api.main as api_main

    class _EmptyScanner:
        def __init__(self, _): pass
        def scan(self, bucket=None, prefix=None): return []

    monkeypatch.setattr("adapters.s3_adapter.S3Scanner", _EmptyScanner)

    body = api_client.post("/scan", json={}).json()
    assert body["status"] == "scan started"
    assert body["queued"] == 0


# ─── /health — scanner field values ──────────────────────────────────────────

def test_health_scanner_disabled_when_use_s3_false(api_client, monkeypatch):
    monkeypatch.setattr("config.settings.USE_S3", False)
    body = api_client.get("/health").json()
    assert body["scanner"] == "disabled"
