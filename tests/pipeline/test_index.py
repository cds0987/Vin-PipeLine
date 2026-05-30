from __future__ import annotations

import importlib
from datetime import datetime, timezone

from models.ingest_job import ChunkResult, IngestJob
from utils.stores import InMemoryMetadataStore, InMemoryVectorStore

index = importlib.import_module("pipeline.05_index")


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _job(doc_id: str = "doc-idx", file_uri: str = "s3://bucket/file.pdf") -> IngestJob:
    return IngestJob(doc_id=doc_id, file_uri=file_uri, file_name="file.pdf")


def _chunks(doc_id: str, n: int = 3) -> list[ChunkResult]:
    return [
        ChunkResult(
            section_id=f"{doc_id}_section_{i:04d}",
            doc_id=doc_id,
            section_content=f"content {i}",
            caption=f"caption {i}",
            embedding=[0.1, 0.2, 0.3],
            source_s3_uri=f"s3://bucket/{doc_id}.pdf",
            markdown_s3_uri=f"s3://bucket/markdown/{doc_id}.md",
        )
        for i in range(n)
    ]


# ─── Return value shape ───────────────────────────────────────────────────────

def test_index_returns_doc_id_status_and_section_count():
    job = _job()
    result = index.run(_chunks(job.doc_id), job, InMemoryVectorStore(), InMemoryMetadataStore())
    assert result["doc_id"] == job.doc_id
    assert result["status"] == "indexed"
    assert result["section_count"] == 3


# ─── Status transitions ───────────────────────────────────────────────────────

def test_index_final_document_status_is_indexed():
    job = _job(doc_id="doc-status")
    metadata_store = InMemoryMetadataStore()
    index.run(_chunks(job.doc_id), job, InMemoryVectorStore(), metadata_store)
    assert metadata_store.get_document(job.doc_id).status == "indexed"


# ─── URIs stamped on every section ───────────────────────────────────────────

def test_index_stamps_source_and_markdown_uri_on_each_section():
    job = _job(doc_id="doc-uri", file_uri="s3://my-bucket/reports/q1.pdf")
    chunks = _chunks(job.doc_id)
    index.run(chunks, job, InMemoryVectorStore(), InMemoryMetadataStore())
    for chunk in chunks:
        assert chunk.metadata["source_s3_uri"] == "s3://my-bucket/reports/q1.pdf"
        assert chunk.metadata["markdown_s3_uri"].endswith(f"{job.doc_id}.md")


# ─── Idempotency — old vectors removed before upsert ─────────────────────────

def test_index_deletes_old_vectors_before_reingest():
    job = _job(doc_id="doc-reimport")
    vector_store = InMemoryVectorStore()
    metadata_store = InMemoryMetadataStore()

    # First run: 5 chunks
    index.run(_chunks(job.doc_id, n=5), job, vector_store, metadata_store)

    # Second run: only 2 chunks — old 5 must not persist
    index.run(_chunks(job.doc_id, n=2), job, vector_store, metadata_store)

    stored = vector_store.search([0.1, 0.2, 0.3], top_k=20)
    doc_chunks = [c for c in stored if c.doc_id == job.doc_id]
    assert len(doc_chunks) == 2


# ─── DocumentRecord fields inferred correctly ─────────────────────────────────

def test_index_infers_file_name_from_uri_when_metadata_missing():
    job = IngestJob(doc_id="doc-fname", file_uri="s3://bucket/reports/annual.pdf")
    metadata_store = InMemoryMetadataStore()
    index.run(_chunks(job.doc_id), job, InMemoryVectorStore(), metadata_store)
    assert metadata_store.get_document(job.doc_id).file_name == "annual.pdf"


def test_index_prefers_file_name_from_metadata_over_uri():
    job = IngestJob(
        doc_id="doc-fname2",
        file_uri="s3://bucket/a1b2c3.pdf",
        file_name="human_readable_name.pdf",
    )
    metadata_store = InMemoryMetadataStore()
    index.run(_chunks(job.doc_id), job, InMemoryVectorStore(), metadata_store)
    assert metadata_store.get_document(job.doc_id).file_name == "human_readable_name.pdf"


def test_index_sets_file_type_from_extension():
    for ext, expected in [("pdf", "pdf"), ("docx", "docx"), ("txt", "txt"), ("html", "html")]:
        job = IngestJob(doc_id=f"doc-{ext}", file_uri=f"s3://bucket/doc.{ext}")
        metadata_store = InMemoryMetadataStore()
        index.run(_chunks(job.doc_id), job, InMemoryVectorStore(), metadata_store)
        assert metadata_store.get_document(job.doc_id).file_type == expected


# ─── s3_last_modified forwarded ───────────────────────────────────────────────

def test_index_forwards_s3_last_modified_to_document_record():
    ts = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    job = IngestJob(doc_id="doc-ts", file_uri="s3://bucket/file.pdf", s3_last_modified=ts)
    metadata_store = InMemoryMetadataStore()
    index.run(_chunks(job.doc_id), job, InMemoryVectorStore(), metadata_store)
    doc = metadata_store.get_document(job.doc_id)
    assert doc.s3_last_modified == ts


# ─── Sections upserted to vector store ───────────────────────────────────────

def test_index_sections_are_searchable_after_indexing():
    job = _job(doc_id="doc-search")
    vector_store = InMemoryVectorStore()
    index.run(_chunks(job.doc_id), job, vector_store, InMemoryMetadataStore())
    results = vector_store.search([0.1, 0.2, 0.3], top_k=10)
    assert any(r.doc_id == job.doc_id for r in results)


# ─── duration_seconds accepted without error ──────────────────────────────────

def test_index_accepts_duration_seconds_kwarg():
    job = _job(doc_id="doc-dur")
    result = index.run(
        _chunks(job.doc_id), job,
        InMemoryVectorStore(), InMemoryMetadataStore(),
        duration_seconds=4.2,
    )
    assert result["status"] == "indexed"
