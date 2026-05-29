from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from models.ingest_job import ChunkResult, DocumentRecord, IngestJob
from utils.stores import MetadataStore, VectorStore


def run(
    chunks: list[ChunkResult],
    job: IngestJob,
    vector_store: VectorStore,
    metadata_store: MetadataStore,
) -> dict:
    vector_store.delete(job.doc_id)
    metadata_store.update_status(job.doc_id, "indexing")
    record = DocumentRecord(
        doc_id=job.doc_id,
        file_uri=job.file_uri,
        file_name=job.metadata.get("file_name") or Path(job.file_uri).name,
        document_type=job.document_type,
        language=job.language,
        status="indexing",
        uploaded_by=(job.permission.owner_id if job.permission else None),
        org_id=(job.permission.org_id if job.permission else None),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    metadata_store.upsert(record)
    if job.permission:
        metadata_store.upsert_permission(job.doc_id, job.permission)
    vector_store.upsert(chunks)
    metadata_store.update_status(job.doc_id, "indexed")
    return {
        "doc_id": job.doc_id,
        "status": "indexed",
        "chunk_count": len(chunks),
    }
