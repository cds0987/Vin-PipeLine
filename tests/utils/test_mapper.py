"""
Mapper tests — covers gaps not in existing suite:
  - doc_id, file_uri forwarded correctly
  - language and document_type from EventMetadata vs defaults
  - file_name and file_size_bytes optional handling (exclude_none)
"""
from __future__ import annotations

from models.events import DocumentUploaded, EventMetadata
from utils.mapper import map_document_uploaded_to_job


def _event(**overrides) -> DocumentUploaded:
    defaults = dict(doc_id="doc-1", s3_uri="s3://bucket/file.pdf", uploaded_by="user-1")
    defaults.update(overrides)
    return DocumentUploaded(**defaults)


# ─── Core fields ──────────────────────────────────────────────────────────────

def test_maps_doc_id():
    job = map_document_uploaded_to_job(_event(doc_id="my-doc"))
    assert job.doc_id == "my-doc"


def test_maps_s3_uri_to_file_uri():
    job = map_document_uploaded_to_job(_event(s3_uri="s3://bucket/report.pdf"))
    assert job.file_uri == "s3://bucket/report.pdf"


# ─── Language ─────────────────────────────────────────────────────────────────

def test_language_from_metadata():
    event = _event(metadata=EventMetadata(language="en"))
    assert map_document_uploaded_to_job(event).language == "en"


def test_language_defaults_to_vi_when_not_set():
    assert map_document_uploaded_to_job(_event()).language == "vi"


# ─── Document type ────────────────────────────────────────────────────────────

def test_document_type_from_metadata():
    event = _event(metadata=EventMetadata(document_type="contract"))
    assert map_document_uploaded_to_job(event).document_type == "contract"


def test_document_type_defaults_to_general():
    assert map_document_uploaded_to_job(_event()).document_type == "general"


# ─── Optional metadata fields ─────────────────────────────────────────────────

def test_file_name_included_when_present():
    event = _event(metadata=EventMetadata(file_name="policy.pdf"))
    job = map_document_uploaded_to_job(event)
    assert job.metadata.get("file_name") == "policy.pdf"


def test_file_name_excluded_when_none():
    event = _event(metadata=EventMetadata(file_name=None))
    job = map_document_uploaded_to_job(event)
    assert "file_name" not in job.metadata


def test_file_size_bytes_included_when_present():
    event = _event(metadata=EventMetadata(file_size_bytes=2048))
    job = map_document_uploaded_to_job(event)
    assert job.metadata.get("file_size_bytes") == 2048


def test_file_size_bytes_excluded_when_none():
    event = _event(metadata=EventMetadata(file_size_bytes=None))
    job = map_document_uploaded_to_job(event)
    assert "file_size_bytes" not in job.metadata


# ─── Multiple metadata fields together ───────────────────────────────────────

def test_all_metadata_fields_together():
    event = _event(metadata=EventMetadata(
        file_name="doc.pdf",
        document_type="invoice",
        language="en",
        file_size_bytes=512,
    ))
    job = map_document_uploaded_to_job(event)
    assert job.language == "en"
    assert job.document_type == "invoice"
    assert job.metadata["file_name"] == "doc.pdf"
    assert job.metadata["file_size_bytes"] == 512
