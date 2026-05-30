from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.domain.documents.models import DocumentRecord, IngestJob
from app.domain.ingestion.policies import is_stale_indexing
from config import settings


class FileMetadataStore:
    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or "data/local_store")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._documents_file = self._base_dir / "documents.json"
        self._jobs_file = self._base_dir / "ingestion_jobs.json"

    def _read(self) -> dict:
        if not self._documents_file.exists():
            return {}
        import json
        return json.loads(self._documents_file.read_text(encoding="utf-8"))

    def _write(self, docs: dict) -> None:
        import json
        self._documents_file.write_text(json.dumps(docs, indent=2, default=str), encoding="utf-8")

    def upsert(self, doc: DocumentRecord) -> None:
        docs = self._read()
        docs[doc.id] = doc.model_dump(mode="json")
        self._write(docs)

    def update_status(self, doc_id: str, status: str) -> None:
        docs = self._read()
        now = datetime.now(timezone.utc).isoformat()
        if doc_id not in docs:
            docs[doc_id] = {
                "id": doc_id, "file_path": "",
                "status": status,
                "uploaded_at": now, "updated_at": now,
            }
        else:
            docs[doc_id]["status"] = status
            docs[doc_id]["updated_at"] = now
        self._write(docs)

    def get_document(self, doc_id: str) -> DocumentRecord | None:
        payload = self._read().get(doc_id)
        return DocumentRecord(**payload) if payload else None

    def get_by_file_path(self, file_path: str) -> DocumentRecord | None:
        for payload in self._read().values():
            if payload.get("file_path") == file_path:
                return DocumentRecord(**payload)
        return None

    def get_by_file_paths(self, file_paths: list[str]) -> dict[str, DocumentRecord]:
        wanted = set(file_paths)
        found: dict[str, DocumentRecord] = {}
        for payload in self._read().values():
            fp = payload.get("file_path")
            if fp in wanted:
                found[fp] = DocumentRecord(**payload)
        return found

    def try_claim_ingest(self, job: IngestJob) -> bool:
        docs = self._read()
        payload = docs.get(job.doc_id)
        if payload:
            existing = DocumentRecord(**payload)
            if existing.status == "indexing" and not is_stale_indexing(existing, settings.STALE_INDEXING_SECONDS):
                return False
            doc = existing.model_copy(
                update={
                    "file_path": job.file_uri,
                    "file_name": job.file_name or existing.file_name,
                    "file_type": Path(job.file_uri).suffix.lstrip(".").lower() or existing.file_type,
                    "document_type": job.document_type,
                    "language": job.language,
                    "status": "indexing",
                    "s3_last_modified": job.s3_last_modified or existing.s3_last_modified,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
        else:
            doc = DocumentRecord(
                id=job.doc_id,
                file_path=job.file_uri,
                file_name=job.file_name,
                file_type=Path(job.file_uri).suffix.lstrip(".").lower() or None,
                document_type=job.document_type,
                language=job.language,
                status="indexing",
                s3_last_modified=job.s3_last_modified,
            )
        docs[job.doc_id] = doc.model_dump(mode="json")
        self._write(docs)
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
        import json

        existing: list[dict] = json.loads(self._jobs_file.read_text(encoding="utf-8")) if self._jobs_file.exists() else []
        now = datetime.now(timezone.utc).isoformat()
        existing.append({
            "doc_id": doc_id,
            "status": status,
            "chunk_count": chunk_count,
            "embedding_model": embedding_model or None,
            "duration_seconds": duration_seconds,
            "error_message": error_message,
            "started_at": now,
            "finished_at": now if status in {"indexed", "failed"} else None,
        })
        self._jobs_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def update_processed(self, doc_id: str, total_chunks: int, processed_at: datetime) -> None:
        docs = self._read()
        payload = docs.get(doc_id)
        if not payload:
            return
        doc = DocumentRecord(**payload).model_copy(
            update={
                "total_chunks": total_chunks,
                "section_count": total_chunks,
                "processed_at": processed_at,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        docs[doc_id] = doc.model_dump(mode="json")
        self._write(docs)
