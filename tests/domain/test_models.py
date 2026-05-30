"""
Tests for domain model field defaults and behavior.

Covers:
  - SectionRecord: new fields heading, heading_path, section_order, access control
  - DocumentRecord: access control fields, backward compat section_count/total_chunks sync
  - MarkdownDocument: basic construction
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.domain.documents.models import DocumentRecord, IngestJob, MarkdownDocument, SectionRecord


# ─── SectionRecord ────────────────────────────────────────────────────────────

def test_section_record_heading_defaults_to_empty():
    s = SectionRecord(section_id="s1", doc_id="d1", section_content="body")
    assert s.heading == ""


def test_section_record_heading_path_defaults_to_empty():
    s = SectionRecord(section_id="s1", doc_id="d1", section_content="body")
    assert s.heading_path == []


def test_section_record_section_order_defaults_to_zero():
    s = SectionRecord(section_id="s1", doc_id="d1", section_content="body")
    assert s.section_order == 0


def test_section_record_title_uses_heading_path():
    s = SectionRecord(
        section_id="s1", doc_id="d1", section_content="body",
        heading_path=["Chapter", "Section"],
    )
    assert s.title == "Chapter > Section"


def test_section_record_title_untitled_when_no_heading_path():
    s = SectionRecord(section_id="s1", doc_id="d1", section_content="body")
    assert s.title == "Untitled"


def test_section_record_access_control_defaults():
    s = SectionRecord(section_id="s1", doc_id="d1", section_content="body")
    assert s.owner_scope is None
    assert s.department_scope is None
    assert s.access_tags == []


def test_section_record_access_control_can_be_set():
    s = SectionRecord(
        section_id="s1", doc_id="d1", section_content="body",
        owner_scope="hr",
        department_scope="legal",
        access_tags=["internal", "confidential"],
    )
    assert s.owner_scope == "hr"
    assert s.department_scope == "legal"
    assert s.access_tags == ["internal", "confidential"]


# ─── DocumentRecord ───────────────────────────────────────────────────────────

def test_document_record_access_control_defaults():
    doc = DocumentRecord(id="d1", file_path="s3://b/f.pdf")
    assert doc.owner_scope is None
    assert doc.department_scope is None
    assert doc.access_tags == []


def test_document_record_section_count_syncs_with_total_chunks():
    doc = DocumentRecord(id="d1", file_path="s3://b/f.pdf", total_chunks=5)
    assert doc.section_count == 5


def test_document_record_total_chunks_syncs_with_section_count():
    doc = DocumentRecord(id="d1", file_path="s3://b/f.pdf", section_count=7)
    assert doc.total_chunks == 7


def test_document_record_source_s3_uri_defaults_to_file_path():
    doc = DocumentRecord(id="d1", file_path="s3://bucket/raw/doc.pdf")
    assert doc.source_s3_uri == "s3://bucket/raw/doc.pdf"


# ─── IngestJob ────────────────────────────────────────────────────────────────

def test_ingest_job_defaults():
    job = IngestJob(doc_id="d1", file_uri="s3://b/f.pdf")
    assert job.language == "vi"
    assert job.document_type == "general"
    assert job.metadata == {}
