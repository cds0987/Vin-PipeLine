from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.domain.documents.models import DocumentRecord, IngestJob, SectionRecord
from app.domain.documents.statuses import DocumentStatus
from app.ports.repositories import DocumentRepository, JobLogRepository
from app.ports.vector_index import SectionIndex
from config import settings

log = logging.getLogger(__name__)


class DocumentIndexService:
    def __init__(
        self,
        section_index: SectionIndex,
        document_repository: DocumentRepository,
        job_log_repository: JobLogRepository,
    ) -> None:
        self._section_index = section_index
        self._document_repository = document_repository
        self._job_log_repository = job_log_repository

    def index_sections(
        self,
        sections: list[SectionRecord],
        job: IngestJob,
        duration_seconds: float = 0.0,
    ) -> dict:
        now = datetime.now(timezone.utc)
        existing = self._document_repository.get_document(job.doc_id)
        uploaded_at = existing.uploaded_at if existing and existing.uploaded_at else now
        file_name = job.file_name or Path(job.file_uri).name
        markdown_s3_uri = sections[0].markdown_s3_uri if sections else (existing.markdown_s3_uri if existing else None)

        self._section_index.delete_document(job.doc_id)
        self._document_repository.update_status(job.doc_id, DocumentStatus.INDEXING)
        self._document_repository.upsert(
            DocumentRecord(
                id=job.doc_id,
                file_path=job.file_uri,
                file_name=file_name,
                file_type=Path(job.file_uri).suffix.lstrip(".").lower() or None,
                document_type=job.document_type,
                title=file_name,
                language=job.language,
                status=DocumentStatus.INDEXING,
                section_count=len(sections),
                markdown_s3_uri=markdown_s3_uri,
                source_s3_uri=job.file_uri,
                parser_version=settings.PARSER_VERSION,
                caption_model=settings.CAPTION_MODEL,
                embedding_model=settings.EMBED_MODEL,
                s3_last_modified=job.s3_last_modified,
                uploaded_at=uploaded_at,
                processed_at=existing.processed_at if existing else None,
                updated_at=now,
            )
        )
        for section in sections:
            section.metadata["file_name"] = file_name
            section.metadata["document_name"] = file_name
            section.metadata["source_s3_uri"] = job.file_uri
            section.metadata["markdown_s3_uri"] = section.markdown_s3_uri or markdown_s3_uri
        t0 = time.perf_counter()
        self._section_index.upsert_sections(sections)
        log.info(
            "sections_indexed doc_id=%s section_count=%d index_backend=%s duration_ms=%d",
            job.doc_id, len(sections),
            self._section_index.__class__.__name__,
            round((time.perf_counter() - t0) * 1000),
        )
        processed_at = datetime.now(timezone.utc)
        self._document_repository.update_status(job.doc_id, DocumentStatus.INDEXED)
        self._document_repository.update_processed(job.doc_id, len(sections), processed_at)
        self._job_log_repository.record_job(
            doc_id=job.doc_id,
            status=DocumentStatus.INDEXED,
            section_count=len(sections),
            embedding_model=settings.EMBED_MODEL,
            duration_seconds=duration_seconds,
        )
        return {
            "doc_id": job.doc_id,
            "status": DocumentStatus.INDEXED,
            "section_count": len(sections),
            "markdown_s3_uri": markdown_s3_uri,
            "source_s3_uri": job.file_uri,
            "embedding_model": settings.EMBED_MODEL,
            "caption_model": settings.CAPTION_MODEL,
            "duration_seconds": duration_seconds,
        }
