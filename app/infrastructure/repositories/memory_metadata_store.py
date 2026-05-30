from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.domain.documents.models import DocumentRecord, IngestJob
from app.domain.ingestion.policies import is_stale_indexing
from config import settings


class InMemoryMetadataStore:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}
        self._jobs: list[dict] = []

    def upsert(self, doc: DocumentRecord) -> None:
        self._documents[doc.id] = doc

    def update_status(self, doc_id: str, status: str) -> None:
        if doc_id in self._documents:
            self._documents[doc_id] = self._documents[doc_id].model_copy(update={"status": status})
        else:
            self._documents[doc_id] = DocumentRecord(id=doc_id, file_path="", status=status)

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        return self._documents.get(doc_id)

    def get_by_file_path(self, file_path: str) -> DocumentRecord | None:
        for doc in self._documents.values():
            if doc.file_path == file_path:
                return doc
        return None

    def get_by_file_paths(self, file_paths: list[str]) -> dict[str, DocumentRecord]:
        wanted = set(file_paths)
        return {doc.file_path: doc for doc in self._documents.values() if doc.file_path in wanted}

    def try_claim_ingest(self, job: IngestJob) -> bool:
        existing = self._documents.get(job.doc_id)
        if existing and existing.status == "indexing" and not is_stale_indexing(existing, settings.STALE_INDEXING_SECONDS):
            return False

        now = datetime.now(timezone.utc)
        if existing is None:
            self._documents[job.doc_id] = DocumentRecord(
                id=job.doc_id,
                file_path=job.file_uri,
                file_name=job.file_name,
                file_type=Path(job.file_uri).suffix.lstrip(".").lower() or None,
                document_type=job.document_type,
                language=job.language,
                status="indexing",
                s3_last_modified=job.s3_last_modified,
                uploaded_at=now,
                updated_at=now,
            )
        else:
            self._documents[job.doc_id] = existing.model_copy(
                update={
                    "file_path": job.file_uri,
                    "file_name": job.file_name or existing.file_name,
                    "file_type": Path(job.file_uri).suffix.lstrip(".").lower() or existing.file_type,
                    "document_type": job.document_type,
                    "language": job.language,
                    "status": "indexing",
                    "s3_last_modified": job.s3_last_modified or existing.s3_last_modified,
                    "updated_at": now,
                }
            )
        return True

    def record_job(
        self,
        doc_id: str,
        status: str,
        chunk_count: int = 0,
        embedding_model: str = "",
        duration_seconds: float = 0.0,
        error_message: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._jobs.append({
            "doc_id": doc_id,
            "status": status,
            "chunk_count": chunk_count,
            "embedding_model": embedding_model or None,
            "duration_seconds": duration_seconds,
            "error_message": error_message,
            "started_at": now,
            "finished_at": now if status in {"indexed", "failed"} else None,
        })

    def update_processed(self, doc_id: str, total_chunks: int, processed_at: datetime) -> None:
        existing = self._documents.get(doc_id)
        if existing is None:
            return
        self._documents[doc_id] = existing.model_copy(
            update={
                "total_chunks": total_chunks,
                "section_count": total_chunks,
                "processed_at": processed_at,
                "updated_at": datetime.now(timezone.utc),
            }
        )
