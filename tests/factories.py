"""
Test data factories — build domain objects with sane defaults.

Usage:
    job = make_ingest_job(doc_id="x", file_uri="s3://b/a.pdf")
    chunk = make_chunk_result(doc_id="x", index=0, content="hello")
    doc = make_document_record(doc_id="x", status="indexed")
"""
from __future__ import annotations

from datetime import datetime, timezone

from config import settings
from models.ingest_job import ChunkResult, DocumentRecord, IngestJob


def make_ingest_job(**kwargs) -> IngestJob:
    defaults: dict = dict(
        doc_id="test-doc-001",
        file_uri="data/sample/policy.txt",
        language="vi",
        document_type="general",
        file_name="policy.txt",
    )
    return IngestJob(**(defaults | kwargs))


def make_chunk_result(index: int = 0, **kwargs) -> ChunkResult:
    doc_id = kwargs.get("doc_id", "test-doc-001")
    defaults: dict = dict(
        chunk_id=f"{doc_id}_chunk_{index:04d}",
        doc_id=doc_id,
        content="sample chunk content for testing",
        embedding=[0.0] * settings.EMBEDDING_DIM,
        page_start=1,
        page_end=1,
    )
    return ChunkResult(**(defaults | kwargs))


def make_chunk_list(doc_id: str = "test-doc-001", count: int = 3) -> list[ChunkResult]:
    return [make_chunk_result(doc_id=doc_id, index=i, content=f"chunk {i} content") for i in range(count)]


def make_document_record(**kwargs) -> DocumentRecord:
    now = datetime.now(timezone.utc)
    defaults: dict = dict(
        id="test-doc-001",
        file_path="s3://test-bucket/raw/policy.pdf",
        file_name="policy.pdf",
        file_type="pdf",
        document_type="general",
        status="indexed",
        uploaded_at=now,
        updated_at=now,
    )
    return DocumentRecord(**(defaults | kwargs))
