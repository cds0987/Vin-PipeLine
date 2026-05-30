from __future__ import annotations

from app.application.ingest.index_sections import DocumentIndexService
from app.infrastructure.repositories.document_repository import MetadataStoreRepository
from app.infrastructure.vector.section_index import VectorStoreSectionIndex
from models.ingest_job import ChunkResult, IngestJob
from utils.stores import MetadataStore, VectorStore


def run(
    chunks: list[ChunkResult],
    job: IngestJob,
    vector_store: VectorStore,
    metadata_store: MetadataStore,
    embedding_model: str = "",
    duration_seconds: float = 0.0,
) -> dict:
    service = DocumentIndexService(
        section_index=VectorStoreSectionIndex(vector_store),
        document_repository=MetadataStoreRepository(metadata_store),
        job_log_repository=MetadataStoreRepository(metadata_store),
    )
    return service.index_sections(chunks, job, duration_seconds=duration_seconds)
