"""
Tests for GET /status/{doc_id}

Covers:
  - 404 when doc_id not found
  - 200 with all required fields for indexed document
  - status values reflected correctly (pending, indexing, indexed, failed)
  - processed_at is None before indexing, set after
"""
from __future__ import annotations

import pytest

from adapters.file_adapter import FileAdapter
from pipeline.run import run


# ── 404 ───────────────────────────────────────────────────────────────────────

def test_status_404_for_unknown_doc(api_client):
    response = api_client.get("/status/does-not-exist")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_status_404_for_empty_store(api_client):
    response = api_client.get("/status/any-id")
    assert response.status_code == 404


# ── 200 field completeness ────────────────────────────────────────────────────

def test_status_200_after_indexing(api_client, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/policy.txt", doc_id="status-full")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    resp = api_client.get("/status/status-full")
    assert resp.status_code == 200
    body = resp.json()

    assert body["doc_id"] == "status-full"
    assert body["status"] == "indexed"
    assert body["file_type"] == "txt"
    assert body["section_count"] is not None and body["section_count"] >= 1
    assert body["uploaded_at"] is not None
    assert body["processed_at"] is not None
    assert "file_path" in body
    assert body["source_s3_uri"] == "data/sample/policy.txt"
    assert body["markdown_s3_uri"].endswith("status-full.md")
    # New fields from refactor
    assert "parser_version" in body
    assert "caption_model" in body
    assert "embedding_model" in body


def test_status_file_path_matches_job_uri(api_client, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/faq.md", doc_id="status-path")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    body = api_client.get("/status/status-path").json()
    assert body["file_path"] == "data/sample/faq.md"


def test_status_file_type_from_extension(api_client, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/faq.md", doc_id="status-md")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    body = api_client.get("/status/status-md").json()
    assert body["file_type"] == "md"


# ── different status values ───────────────────────────────────────────────────

def test_status_reflects_failed_after_failed_ingest(api_client, fake_ai_provider, vector_store, metadata_store):
    metadata_store.update_status("failed-doc", "failed")

    resp = api_client.get("/status/failed-doc")
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"


def test_status_reflects_indexing(api_client, metadata_store):
    metadata_store.update_status("indexing-doc", "indexing")

    resp = api_client.get("/status/indexing-doc")
    assert resp.status_code == 200
    assert resp.json()["status"] == "indexing"


def test_status_processed_at_none_before_complete(api_client, metadata_store):
    from datetime import datetime, timezone
    from models.ingest_job import DocumentRecord

    now = datetime.now(timezone.utc)
    doc = DocumentRecord(
        id="pending-doc", file_path="s3://b/f.pdf", status="pending",
        uploaded_at=now, updated_at=now, processed_at=None,
    )
    metadata_store.upsert(doc)

    body = api_client.get("/status/pending-doc").json()
    assert body["processed_at"] is None
    assert body["status"] == "pending"
