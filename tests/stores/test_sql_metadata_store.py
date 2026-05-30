"""
Tests for SQLMetadataStore — uses SQLite in-memory to avoid requiring Postgres.
Covers every public method: upsert, update_status, get_document, get_by_file_path,
get_by_file_paths, try_claim_ingest, record_job, update_processed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from models.ingest_job import DocumentRecord, IngestJob
from utils.stores import SQLMetadataStore


@pytest.fixture
def store(tmp_path):
    return SQLMetadataStore(db_url=f"sqlite:///{tmp_path}/test.db")


def _job(doc_id: str = "doc1", uri: str = "s3://bucket/file.pdf") -> IngestJob:
    return IngestJob(doc_id=doc_id, file_uri=uri, file_name="file.pdf", document_type="hr")


def _doc(doc_id: str = "doc1") -> DocumentRecord:
    now = datetime.now(timezone.utc)
    return DocumentRecord(
        id=doc_id, file_path=f"s3://bucket/{doc_id}.pdf",
        file_name=f"{doc_id}.pdf", file_type="pdf",
        document_type="hr", status="pending",
        uploaded_at=now, updated_at=now,
    )


# ── upsert / get_document ────────────────────────────────────────────────────

def test_upsert_and_get_document(store):
    doc = _doc()
    store.upsert(doc)
    retrieved = store.get_document(doc.id)
    assert retrieved is not None
    assert retrieved.id == doc.id
    assert retrieved.status == "pending"
    assert retrieved.file_name == doc.file_name


def test_get_document_returns_none_for_unknown(store):
    assert store.get_document("nonexistent") is None


def test_upsert_replaces_existing(store):
    doc = _doc()
    store.upsert(doc)
    updated = doc.model_copy(update={"status": "indexed", "section_count": 42})
    store.upsert(updated)
    retrieved = store.get_document(doc.id)
    assert retrieved.status == "indexed"
    assert retrieved.section_count == 42
    assert retrieved.total_chunks == 42


# ── update_status ─────────────────────────────────────────────────────────────

def test_update_status_changes_existing_doc(store):
    store.upsert(_doc())
    store.update_status("doc1", "indexed")
    assert store.get_document("doc1").status == "indexed"


def test_update_status_creates_stub_for_unknown_doc(store):
    store.update_status("new-doc", "failed")
    doc = store.get_document("new-doc")
    assert doc is not None
    assert doc.status == "failed"


def test_update_status_cycles_pending_indexing_indexed(store):
    store.upsert(_doc())
    for status in ("indexing", "indexed"):
        store.update_status("doc1", status)
        assert store.get_document("doc1").status == status


# ── get_by_file_path ──────────────────────────────────────────────────────────

def test_get_by_file_path_finds_doc(store):
    doc = _doc()
    store.upsert(doc)
    found = store.get_by_file_path(doc.file_path)
    assert found is not None
    assert found.id == doc.id


def test_get_by_file_path_returns_none_when_not_found(store):
    assert store.get_by_file_path("s3://bucket/notexist.pdf") is None


# ── get_by_file_paths ─────────────────────────────────────────────────────────

def test_get_by_file_paths_returns_matching_docs(store):
    docs = [_doc(f"doc{i}") for i in range(3)]
    for d in docs:
        store.upsert(d)

    paths = [docs[0].file_path, docs[2].file_path]
    result = store.get_by_file_paths(paths)
    assert set(result.keys()) == {docs[0].file_path, docs[2].file_path}


def test_get_by_file_paths_empty_input_returns_empty(store):
    assert store.get_by_file_paths([]) == {}


def test_get_by_file_paths_none_matching_returns_empty(store):
    assert store.get_by_file_paths(["s3://nothing/here.pdf"]) == {}


# ── try_claim_ingest ──────────────────────────────────────────────────────────

def test_try_claim_ingest_new_doc_returns_true(store):
    job = _job()
    assert store.try_claim_ingest(job) is True
    doc = store.get_document(job.doc_id)
    assert doc.status == "indexing"
    assert doc.file_name == job.file_name
    assert doc.document_type == job.document_type


def test_try_claim_ingest_indexing_not_stale_returns_false(store, monkeypatch):
    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 3600)
    job = _job()
    store.try_claim_ingest(job)               # first claim → indexing
    assert store.try_claim_ingest(job) is False  # second → blocked


def test_try_claim_ingest_stale_indexing_reclaims(store, monkeypatch):
    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 0)
    job = _job()
    store.try_claim_ingest(job)
    assert store.try_claim_ingest(job) is True   # stale=0 → always stale


def test_try_claim_ingest_failed_doc_reclaims(store, monkeypatch):
    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 3600)
    job = _job()
    store.try_claim_ingest(job)
    store.update_status(job.doc_id, "failed")
    assert store.try_claim_ingest(job) is True   # failed → can retry


def test_try_claim_ingest_indexed_doc_reclaims(store, monkeypatch):
    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 3600)
    job = _job()
    store.try_claim_ingest(job)
    store.update_status(job.doc_id, "indexed")
    assert store.try_claim_ingest(job) is True   # indexed → can re-index


def test_try_claim_ingest_sets_file_type_from_uri(store):
    job = IngestJob(doc_id="doc-type", file_uri="s3://b/report.pdf", file_name="report.pdf")
    store.try_claim_ingest(job)
    assert store.get_document("doc-type").file_type == "pdf"


# ── record_job ────────────────────────────────────────────────────────────────

def test_record_job_stores_entry(store):
    store.record_job("doc1", "indexed", chunk_count=5, embedding_model="ada", duration_seconds=1.5)
    # No assertion on retrieval (no get_jobs method), but should not raise


def test_record_job_with_error_message(store):
    store.record_job("doc1", "failed", error_message="embed API down")


def test_record_job_multiple_entries_per_doc(store):
    for _ in range(3):
        store.record_job("doc1", "failed", error_message="retry")
    store.record_job("doc1", "indexed", chunk_count=7)


# ── update_processed ──────────────────────────────────────────────────────────

def test_update_processed_sets_section_count_and_processed_at(store):
    store.upsert(_doc())
    processed_at = datetime.now(timezone.utc)
    store.update_processed("doc1", total_chunks=12, processed_at=processed_at)
    doc = store.get_document("doc1")
    assert doc.section_count == 12
    assert doc.total_chunks == 12
    assert doc.processed_at is not None


def test_update_processed_noop_for_unknown_doc(store):
    store.update_processed("nonexistent", total_chunks=5, processed_at=datetime.now(timezone.utc))
    assert store.get_document("nonexistent") is None


# ── persistence across connections ───────────────────────────────────────────

def test_data_persists_across_store_instances(tmp_path):
    db_url = f"sqlite:///{tmp_path}/persist.db"
    s1 = SQLMetadataStore(db_url=db_url)
    s1.upsert(_doc("persisted-doc"))

    s2 = SQLMetadataStore(db_url=db_url)
    assert s2.get_document("persisted-doc") is not None
