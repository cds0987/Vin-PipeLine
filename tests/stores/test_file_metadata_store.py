"""
Tests for FileMetadataStore — uses tmp_path (no external services).
Covers all public methods and verifies JSON persistence on disk.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from models.ingest_job import DocumentRecord, IngestJob
from utils.stores import FileMetadataStore


@pytest.fixture
def store(tmp_path):
    return FileMetadataStore(base_dir=str(tmp_path / "store"))


def _job(doc_id: str = "doc1", uri: str = "s3://b/file.txt") -> IngestJob:
    return IngestJob(doc_id=doc_id, file_uri=uri, file_name="file.txt", document_type="hr")


def _doc(doc_id: str = "doc1", status: str = "pending") -> DocumentRecord:
    now = datetime.now(timezone.utc)
    return DocumentRecord(
        id=doc_id, file_path=f"s3://b/{doc_id}.pdf",
        file_name=f"{doc_id}.pdf", file_type="pdf",
        document_type="hr", status=status,
        uploaded_at=now, updated_at=now,
    )


# ── upsert / get_document ────────────────────────────────────────────────────

def test_upsert_and_get_document(store):
    doc = _doc()
    store.upsert(doc)
    got = store.get_document(doc.id)
    assert got is not None
    assert got.id == doc.id
    assert got.status == "pending"


def test_get_document_returns_none_for_unknown(store):
    assert store.get_document("nope") is None


def test_upsert_replaces_existing(store):
    store.upsert(_doc())
    store.upsert(_doc(status="indexed"))
    assert store.get_document("doc1").status == "indexed"


def test_multiple_docs_stored_independently(store):
    for i in range(5):
        store.upsert(_doc(f"doc{i}"))
    for i in range(5):
        assert store.get_document(f"doc{i}") is not None


# ── update_status ─────────────────────────────────────────────────────────────

def test_update_status_changes_status(store):
    store.upsert(_doc())
    store.update_status("doc1", "indexed")
    assert store.get_document("doc1").status == "indexed"


def test_update_status_creates_minimal_doc_for_unknown(store):
    store.update_status("brand-new", "failed")
    doc = store.get_document("brand-new")
    assert doc is not None
    assert doc.status == "failed"


# ── get_by_file_path ──────────────────────────────────────────────────────────

def test_get_by_file_path_finds_doc(store):
    doc = _doc()
    store.upsert(doc)
    found = store.get_by_file_path(doc.file_path)
    assert found is not None
    assert found.id == doc.id


def test_get_by_file_path_returns_none_when_missing(store):
    assert store.get_by_file_path("s3://b/missing.pdf") is None


# ── get_by_file_paths ─────────────────────────────────────────────────────────

def test_get_by_file_paths_batch_lookup(store):
    docs = [_doc(f"d{i}") for i in range(4)]
    for d in docs:
        store.upsert(d)
    paths = [docs[0].file_path, docs[3].file_path]
    result = store.get_by_file_paths(paths)
    assert set(result.keys()) == {docs[0].file_path, docs[3].file_path}


def test_get_by_file_paths_empty_input(store):
    assert store.get_by_file_paths([]) == {}


# ── try_claim_ingest ──────────────────────────────────────────────────────────

def test_try_claim_ingest_new_doc_returns_true(store):
    job = _job()
    assert store.try_claim_ingest(job) is True
    doc = store.get_document(job.doc_id)
    assert doc.status == "indexing"
    assert doc.document_type == "hr"


def test_try_claim_ingest_active_indexing_returns_false(store, monkeypatch):
    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 3600)
    job = _job()
    store.try_claim_ingest(job)
    assert store.try_claim_ingest(job) is False


def test_try_claim_ingest_stale_reclaims(store, monkeypatch):
    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 0)
    job = _job()
    store.try_claim_ingest(job)
    assert store.try_claim_ingest(job) is True


def test_try_claim_ingest_failed_can_retry(store, monkeypatch):
    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 3600)
    job = _job()
    store.try_claim_ingest(job)
    store.update_status(job.doc_id, "failed")
    assert store.try_claim_ingest(job) is True


# ── record_job ────────────────────────────────────────────────────────────────

def test_record_job_appends_to_file(store, tmp_path):
    import json
    store.record_job("doc1", "indexed", chunk_count=5, embedding_model="m", duration_seconds=2.0)
    store.record_job("doc1", "indexed", chunk_count=5)
    jobs_file = tmp_path / "store" / "ingestion_jobs.json"
    jobs = json.loads(jobs_file.read_text())
    assert len(jobs) == 2
    assert jobs[0]["chunk_count"] == 5


def test_record_job_error_message_stored(store, tmp_path):
    import json
    store.record_job("doc1", "failed", error_message="timeout")
    jobs_file = tmp_path / "store" / "ingestion_jobs.json"
    jobs = json.loads(jobs_file.read_text())
    assert jobs[0]["error_message"] == "timeout"


# ── update_processed ──────────────────────────────────────────────────────────

def test_update_processed_sets_section_count_and_timestamp(store):
    store.upsert(_doc())
    now = datetime.now(timezone.utc)
    store.update_processed("doc1", total_chunks=8, processed_at=now)
    doc = store.get_document("doc1")
    assert doc.section_count == 8
    assert doc.total_chunks == 8
    assert doc.processed_at is not None


def test_update_processed_noop_for_missing_doc(store):
    store.update_processed("ghost", total_chunks=3, processed_at=datetime.now(timezone.utc))
    assert store.get_document("ghost") is None


# ── persistence ───────────────────────────────────────────────────────────────

def test_data_survives_new_store_instance(tmp_path):
    base = str(tmp_path / "persistent")
    s1 = FileMetadataStore(base_dir=base)
    s1.upsert(_doc("persisted"))

    s2 = FileMetadataStore(base_dir=base)
    assert s2.get_document("persisted") is not None
    assert s2.get_document("persisted").file_name == "persisted.pdf"


def test_status_update_persists_across_instances(tmp_path):
    base = str(tmp_path / "status-persist")
    s1 = FileMetadataStore(base_dir=base)
    s1.upsert(_doc())
    s1.update_status("doc1", "indexed")

    s2 = FileMetadataStore(base_dir=base)
    assert s2.get_document("doc1").status == "indexed"
