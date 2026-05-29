from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from config import settings
from models.ingest_job import ChunkResult, DocumentRecord, IngestJob
from utils.stores import MetadataStore, VectorStore


def run(
    chunks: list[ChunkResult],
    job: IngestJob,
    vector_store: VectorStore,
    metadata_store: MetadataStore,
    embedding_model: str = "",
    duration_seconds: float = 0.0,
) -> dict:
    now = datetime.now(timezone.utc)
    existing = metadata_store.get_document(job.doc_id)
    uploaded_at = existing.uploaded_at if existing and existing.uploaded_at else now

    vector_store.delete(job.doc_id)
    metadata_store.update_status(job.doc_id, "indexing")

    file_name = job.file_name or Path(job.file_uri).name
    record = DocumentRecord(
        id=job.doc_id,
        file_path=job.file_uri,
        file_name=file_name,
        file_type=Path(job.file_uri).suffix.lstrip(".").lower() or None,
        document_type=job.document_type,
        title=file_name,
        language=job.language,
        status="indexing",
        s3_last_modified=job.s3_last_modified,
        uploaded_at=uploaded_at,
        processed_at=existing.processed_at if existing else None,
        updated_at=now,
    )
    metadata_store.upsert(record)

    # Stamp s3_uri vào mỗi chunk — Qdrant payload sẽ trả về trong search results
    for chunk in chunks:
        chunk.metadata["s3_uri"] = job.file_uri

    vector_store.upsert(chunks)

    processed_at = datetime.now(timezone.utc)
    metadata_store.update_status(job.doc_id, "indexed")

    metadata_store.update_processed(job.doc_id, len(chunks), processed_at)

    metadata_store.record_job(
        doc_id=job.doc_id,
        status="indexed",
        chunk_count=len(chunks),
        embedding_model=embedding_model or settings.EMBED_MODEL,
        duration_seconds=duration_seconds,
    )

    return {
        "doc_id": job.doc_id,
        "status": "indexed",
        "chunk_count": len(chunks),
    }
