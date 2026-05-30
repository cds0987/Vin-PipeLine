from __future__ import annotations

from datetime import datetime

from app.domain.documents.models import DocumentRecord, IngestJob
from app.ports.repositories import DocumentRepository, IngestClaimRepository, JobLogRepository
from utils.stores import MetadataStore


class MetadataStoreRepository(DocumentRepository, IngestClaimRepository, JobLogRepository):
    def __init__(self, metadata_store: MetadataStore) -> None:
        self._metadata_store = metadata_store

    def upsert(self, doc: DocumentRecord) -> None:
        self._metadata_store.upsert(doc)

    def update_status(self, doc_id: str, status: str) -> None:
        self._metadata_store.update_status(doc_id, status)

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        doc = self._metadata_store.get_document(doc_id)
        return DocumentRecord(**doc.model_dump()) if doc else None

    def get_by_file_path(self, file_path: str) -> DocumentRecord | None:
        doc = self._metadata_store.get_by_file_path(file_path)
        return DocumentRecord(**doc.model_dump()) if doc else None

    def get_by_file_paths(self, file_paths: list[str]) -> dict[str, DocumentRecord]:
        return {
            key: DocumentRecord(**value.model_dump())
            for key, value in self._metadata_store.get_by_file_paths(file_paths).items()
        }

    def try_claim_ingest(self, job: IngestJob) -> bool:
        return self._metadata_store.try_claim_ingest(job)

    def update_processed(self, doc_id: str, section_count: int, processed_at: datetime) -> None:
        self._metadata_store.update_processed(doc_id, section_count, processed_at)

    def record_job(
        self,
        doc_id: str,
        status: str,
        section_count: int = 0,
        embedding_model: str = "",
        duration_seconds: float = 0.0,
        error_message: str | None = None,
    ) -> None:
        self._metadata_store.record_job(
            doc_id=doc_id,
            status=status,
            chunk_count=section_count,
            embedding_model=embedding_model,
            duration_seconds=duration_seconds,
            error_message=error_message,
        )
