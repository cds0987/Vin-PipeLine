from __future__ import annotations

import uuid as _uuid_module
from datetime import datetime, timezone
from pathlib import Path

from app.domain.documents.models import DocumentRecord, IngestJob
from app.domain.ingestion.policies import is_stale_indexing
from config import settings


class SQLMetadataStore:
    def __init__(self, db_url: str | None = None) -> None:
        from sqlalchemy import create_engine, inspect
        from db.schema import documents, ingestion_jobs, metadata as schema_metadata

        self._engine = create_engine(
            db_url or settings.DB_URL,
            future=True,
            pool_pre_ping=True,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
        )
        self._metadata = schema_metadata
        self._documents = documents
        self._jobs = ingestion_jobs
        self._metadata.create_all(self._engine)
        inspector = inspect(self._engine)
        self._document_columns = {column["name"] for column in inspector.get_columns("documents")}

    def _document_payload(self, doc: DocumentRecord) -> dict:
        payload = doc.model_dump()
        return {key: value for key, value in payload.items() if key in self._document_columns}

    def _document_from_row(self, row: dict) -> DocumentRecord:
        return DocumentRecord(**dict(row))

    def upsert(self, doc: DocumentRecord) -> None:
        payload = self._document_payload(doc)
        with self._engine.begin() as conn:
            updated = conn.execute(
                self._documents.update()
                .where(self._documents.c.id == doc.id)
                .values(**payload)
            )
            if updated.rowcount == 0:
                conn.execute(self._documents.insert().values(**payload))

    def update_status(self, doc_id: str, status: str) -> None:
        from sqlalchemy import select

        with self._engine.begin() as conn:
            row = conn.execute(
                select(self._documents).where(self._documents.c.id == doc_id)
            ).mappings().first()
            if row is None:
                conn.execute(self._documents.insert().values(
                    id=doc_id, file_path="", file_name=None, file_type=None,
                    document_type="general", language="vi", status=status,
                    uploaded_at=datetime.now(timezone.utc),
                    processed_at=None, updated_at=datetime.now(timezone.utc),
                ))
            else:
                conn.execute(
                    self._documents.update()
                    .where(self._documents.c.id == doc_id)
                    .values(status=status, updated_at=datetime.now(timezone.utc))
                )

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        from sqlalchemy import select

        with self._engine.begin() as conn:
            row = conn.execute(
                select(self._documents).where(self._documents.c.id == doc_id)
            ).mappings().first()
        return self._document_from_row(row) if row else None

    def get_by_file_path(self, file_path: str) -> DocumentRecord | None:
        from sqlalchemy import select

        with self._engine.begin() as conn:
            row = conn.execute(
                select(self._documents).where(self._documents.c.file_path == file_path)
            ).mappings().first()
        return self._document_from_row(row) if row else None

    def get_by_file_paths(self, file_paths: list[str]) -> dict[str, DocumentRecord]:
        from sqlalchemy import select

        if not file_paths:
            return {}
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(self._documents).where(self._documents.c.file_path.in_(file_paths))
            ).mappings().all()
        return {row["file_path"]: self._document_from_row(row) for row in rows}

    def try_claim_ingest(self, job: IngestJob) -> bool:
        from sqlalchemy import select

        now = datetime.now(timezone.utc)
        with self._engine.begin() as conn:
            row = conn.execute(
                select(self._documents).where(self._documents.c.id == job.doc_id)
            ).mappings().first()
            if row is None:
                conn.execute(
                    self._documents.insert().values(
                        id=job.doc_id,
                        file_path=job.file_uri,
                        file_name=job.file_name,
                        file_type=Path(job.file_uri).suffix.lstrip(".").lower() or None,
                        document_type=job.document_type,
                        language=job.language,
                        status="indexing",
                        s3_last_modified=job.s3_last_modified,
                        uploaded_at=now,
                        processed_at=None,
                        updated_at=now,
                    )
                )
                return True

            existing = DocumentRecord(**dict(row))
            if existing.status == "indexing" and not is_stale_indexing(existing, settings.STALE_INDEXING_SECONDS):
                return False

            conn.execute(
                self._documents.update()
                .where(self._documents.c.id == job.doc_id)
                .values(
                    file_path=job.file_uri,
                    file_name=job.file_name or existing.file_name,
                    file_type=Path(job.file_uri).suffix.lstrip(".").lower() or existing.file_type,
                    document_type=job.document_type,
                    language=job.language,
                    status="indexing",
                    s3_last_modified=job.s3_last_modified or existing.s3_last_modified,
                    updated_at=now,
                )
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
        now = datetime.now(timezone.utc)
        with self._engine.begin() as conn:
            conn.execute(self._jobs.insert().values(
                id=str(_uuid_module.uuid4()),
                doc_id=doc_id,
                status=status,
                chunk_count=chunk_count,
                embedding_model=embedding_model or None,
                duration_seconds=duration_seconds,
                error_message=error_message,
                started_at=now,
                finished_at=now if status in ("indexed", "failed") else None,
            ))

    def update_processed(self, doc_id: str, total_chunks: int, processed_at: datetime) -> None:
        values: dict = {
            "total_chunks": total_chunks,
            "processed_at": processed_at,
            "updated_at": datetime.now(timezone.utc),
        }
        if "section_count" in self._document_columns:
            values["section_count"] = total_chunks
        with self._engine.begin() as conn:
            conn.execute(
                self._documents.update()
                .where(self._documents.c.id == doc_id)
                .values(**values)
            )
