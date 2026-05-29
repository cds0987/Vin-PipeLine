"""
S3Scanner tests — zero existing coverage.

All tests mock the boto3 client so no real S3 connection is needed.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from adapters.s3_adapter import S3Scanner, _uri_to_doc_id
from models.ingest_job import DocumentRecord
from utils.stores import InMemoryMetadataStore


# ─── _uri_to_doc_id ───────────────────────────────────────────────────────────

def test_doc_id_is_md5_of_s3_uri():
    uri = "s3://bucket/path/to/file.pdf"
    assert _uri_to_doc_id(uri) == hashlib.md5(uri.encode()).hexdigest()


def test_doc_id_is_stable_across_calls():
    uri = "s3://bucket/file.pdf"
    assert _uri_to_doc_id(uri) == _uri_to_doc_id(uri)


def test_doc_id_differs_for_different_uris():
    assert _uri_to_doc_id("s3://bucket/a.pdf") != _uri_to_doc_id("s3://bucket/b.pdf")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ts(year: int = 2026, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


def _s3_obj(key: str, last_modified: datetime | None = None) -> dict:
    return {"Key": key, "LastModified": last_modified or _ts()}


def _scan(
    objects: list[dict],
    metadata_store: InMemoryMetadataStore | None = None,
    prefix: str = "",
) -> list:
    """Run scanner against a faked S3 page containing *objects*."""
    store = metadata_store or InMemoryMetadataStore()
    scanner = S3Scanner(store)
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [{"Contents": objects}]
    fake_client = MagicMock()
    fake_client.get_paginator.return_value = fake_paginator

    with patch("adapters.s3_adapter._s3_client", return_value=fake_client):
        return scanner.scan(bucket="test-bucket", prefix=prefix)


def _doc(doc_id: str, file_path: str, status: str,
         s3_last_modified: datetime | None = None) -> DocumentRecord:
    now = datetime.now(timezone.utc)
    return DocumentRecord(
        id=doc_id, file_path=file_path, status=status,
        s3_last_modified=s3_last_modified,
        uploaded_at=now, updated_at=now,
    )


# ─── New file → create job ────────────────────────────────────────────────────

def test_new_pdf_creates_job():
    jobs = _scan([_s3_obj("raw/report.pdf")])
    assert len(jobs) == 1
    assert jobs[0].file_uri == "s3://test-bucket/raw/report.pdf"


def test_job_doc_id_equals_md5_of_uri():
    uri = "s3://test-bucket/raw/report.pdf"
    jobs = _scan([_s3_obj("raw/report.pdf")])
    assert jobs[0].doc_id == _uri_to_doc_id(uri)


def test_job_metadata_contains_file_name():
    jobs = _scan([_s3_obj("raw/my_policy.pdf")])
    assert jobs[0].file_name == "my_policy.pdf"


def test_job_carries_s3_last_modified():
    ts = _ts(2026, 3, 15)
    jobs = _scan([_s3_obj("raw/file.pdf", last_modified=ts)])
    assert jobs[0].s3_last_modified == ts


def test_job_document_type_derived_from_first_path_segment_after_prefix():
    jobs = _scan([_s3_obj("raw/contracts/master-service-agreement.pdf")], prefix="raw/")
    assert jobs[0].document_type == "contracts"


def test_job_document_type_defaults_to_general_when_file_is_at_prefix_root():
    jobs = _scan([_s3_obj("raw/report.pdf")], prefix="raw/")
    assert jobs[0].document_type == "general"


# ─── Already indexed, unchanged → skip ───────────────────────────────────────

def test_skips_already_indexed_unchanged_file():
    uri = "s3://test-bucket/raw/report.pdf"
    ts = _ts(2026, 1, 1)
    store = InMemoryMetadataStore()
    store.upsert(_doc(_uri_to_doc_id(uri), uri, "indexed", s3_last_modified=ts))
    jobs = _scan([_s3_obj("raw/report.pdf", last_modified=ts)], store)
    assert jobs == []


# ─── Currently indexing → skip ────────────────────────────────────────────────

def test_skips_file_being_indexed():
    uri = "s3://test-bucket/raw/report.pdf"
    store = InMemoryMetadataStore()
    store.upsert(_doc(_uri_to_doc_id(uri), uri, "indexing"))
    jobs = _scan([_s3_obj("raw/report.pdf")], store)
    assert jobs == []


def test_retries_stale_indexing_file(monkeypatch):
    uri = "s3://test-bucket/raw/report.pdf"
    old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    store = InMemoryMetadataStore()
    stale_doc = _doc(_uri_to_doc_id(uri), uri, "indexing", s3_last_modified=old_ts)
    stale_doc = stale_doc.model_copy(update={"updated_at": datetime(2020, 1, 1, tzinfo=timezone.utc)})
    store.upsert(stale_doc)

    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 1)
    jobs = _scan([_s3_obj("raw/report.pdf", last_modified=_ts(2026, 2, 1))], store)

    assert len(jobs) == 1
    assert jobs[0].doc_id == stale_doc.id


# ─── Failed / pending → retry with existing doc_id ───────────────────────────

@pytest.mark.parametrize("status", ["failed", "pending"])
def test_retries_failed_or_pending_with_existing_doc_id(status):
    uri = "s3://test-bucket/raw/report.pdf"
    existing_id = _uri_to_doc_id(uri)
    store = InMemoryMetadataStore()
    store.upsert(_doc(existing_id, uri, status))
    jobs = _scan([_s3_obj("raw/report.pdf")], store)
    assert len(jobs) == 1
    assert jobs[0].doc_id == existing_id


# ─── s3_last_modified newer → re-ingest ──────────────────────────────────────

def test_reingests_when_file_has_newer_modified_time():
    uri = "s3://test-bucket/raw/report.pdf"
    old_ts = _ts(2026, 1, 1)
    new_ts = _ts(2026, 6, 1)
    store = InMemoryMetadataStore()
    store.upsert(_doc(_uri_to_doc_id(uri), uri, "indexed", s3_last_modified=old_ts))
    jobs = _scan([_s3_obj("raw/report.pdf", last_modified=new_ts)], store)
    assert len(jobs) == 1


def test_does_not_reingest_when_timestamp_equal():
    uri = "s3://test-bucket/raw/report.pdf"
    ts = _ts(2026, 4, 10)
    store = InMemoryMetadataStore()
    store.upsert(_doc(_uri_to_doc_id(uri), uri, "indexed", s3_last_modified=ts))
    jobs = _scan([_s3_obj("raw/report.pdf", last_modified=ts)], store)
    assert jobs == []


# ─── Unsupported / supported extensions ──────────────────────────────────────

def test_skips_unsupported_extension():
    assert _scan([_s3_obj("data/spreadsheet.csv")]) == []


def test_skips_directory_like_keys():
    # Keys ending in / are S3 directory markers
    assert _scan([_s3_obj("raw/subdir/")]) == []


@pytest.mark.parametrize("filename", [
    "doc.pdf", "doc.docx", "doc.txt", "doc.md",
    "doc.html", "doc.htm", "doc.png", "doc.jpg",
    "doc.jpeg", "doc.webp", "doc.bmp", "doc.tiff",
])
def test_all_supported_extensions_create_jobs(filename):
    jobs = _scan([_s3_obj(f"raw/{filename}")])
    assert len(jobs) == 1


# ─── Error handling ───────────────────────────────────────────────────────────

def test_s3_client_init_failure_returns_empty():
    scanner = S3Scanner(InMemoryMetadataStore())
    with patch("adapters.s3_adapter._s3_client", side_effect=Exception("no credentials")):
        assert scanner.scan(bucket="bucket", prefix="") == []


def test_paginator_failure_returns_empty():
    scanner = S3Scanner(InMemoryMetadataStore())
    fake_client = MagicMock()
    fake_paginator = MagicMock()
    fake_paginator.paginate.side_effect = Exception("S3 down")
    fake_client.get_paginator.return_value = fake_paginator
    with patch("adapters.s3_adapter._s3_client", return_value=fake_client):
        assert scanner.scan(bucket="bucket", prefix="") == []


def test_empty_bucket_contents_returns_empty():
    scanner = S3Scanner(InMemoryMetadataStore())
    fake_client = MagicMock()
    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [{}]  # no "Contents" key
    fake_client.get_paginator.return_value = fake_paginator
    with patch("adapters.s3_adapter._s3_client", return_value=fake_client):
        assert scanner.scan(bucket="bucket", prefix="") == []


# ─── Multiple files in one scan ───────────────────────────────────────────────

def test_multiple_new_files_all_queued():
    objs = [_s3_obj(f"raw/doc{i}.pdf") for i in range(5)]
    jobs = _scan(objs)
    assert len(jobs) == 5


def test_mixed_new_and_indexed_only_new_queued():
    uri_a = "s3://test-bucket/raw/a.pdf"
    uri_b = "s3://test-bucket/raw/b.pdf"
    ts = _ts()
    store = InMemoryMetadataStore()
    store.upsert(_doc(_uri_to_doc_id(uri_a), uri_a, "indexed", s3_last_modified=ts))

    jobs = _scan(
        [_s3_obj("raw/a.pdf", last_modified=ts), _s3_obj("raw/b.pdf", last_modified=ts)],
        store,
    )
    assert len(jobs) == 1
    assert jobs[0].file_uri == uri_b
