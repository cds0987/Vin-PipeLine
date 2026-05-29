from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from config import settings
from models.ingest_job import ChunkResult, DocumentRecord, IngestJob

log = logging.getLogger(__name__)


class VectorStore(Protocol):
    @abstractmethod
    def upsert(self, chunks: list[ChunkResult]) -> None: ...

    @abstractmethod
    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[ChunkResult]: ...

    @abstractmethod
    def delete(self, doc_id: str) -> None: ...


class MetadataStore(Protocol):
    @abstractmethod
    def upsert(self, doc: DocumentRecord) -> None: ...

    @abstractmethod
    def update_status(self, doc_id: str, status: str) -> None: ...

    @abstractmethod
    def get_document(self, doc_id: str) -> DocumentRecord | None: ...

    @abstractmethod
    def get_by_file_path(self, file_path: str) -> DocumentRecord | None: ...

    @abstractmethod
    def get_by_file_paths(self, file_paths: list[str]) -> dict[str, DocumentRecord]: ...

    @abstractmethod
    def try_claim_ingest(self, job: IngestJob) -> bool: ...

    @abstractmethod
    def record_job(
        self,
        doc_id: str,
        status: str,
        chunk_count: int = 0,
        embedding_model: str = "",
        duration_seconds: float = 0.0,
        error_message: str | None = None,
    ) -> None: ...

    @abstractmethod
    def update_processed(
        self,
        doc_id: str,
        total_chunks: int,
        processed_at: datetime,
    ) -> None: ...


def _is_stale_indexing(doc: DocumentRecord) -> bool:
    if doc.status != "indexing":
        return False
    if settings.STALE_INDEXING_SECONDS == 0:
        return True
    updated_at = doc.updated_at or doc.uploaded_at
    return datetime.now(timezone.utc) - updated_at >= timedelta(seconds=settings.STALE_INDEXING_SECONDS)


# ─── Vector store implementations ────────────────────────────────────────────

class QdrantStore:
    def __init__(self) -> None:
        import uuid as _uuid
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        self._uuid = _uuid
        qdrant_url = settings.QDRANT_URL or None
        qdrant_api_key = settings.QDRANT_API_KEY or None
        if qdrant_url:
            self._client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        else:
            self._client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

        self._collection = settings.QDRANT_COLLECTION
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=settings.EMBEDDING_DIM, distance=Distance.COSINE),
            )
        else:
            info = self._client.get_collection(self._collection)
            actual_size = getattr(getattr(info.config.params, "vectors", None), "size", None)
            if actual_size is not None and actual_size != settings.EMBEDDING_DIM:
                raise ValueError(
                    f"Qdrant collection '{self._collection}' dimension mismatch: "
                    f"expected {settings.EMBEDDING_DIM}, got {actual_size}"
                )
        self._client.create_payload_index(
            collection_name=self._collection,
            field_name="doc_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    def _point_id(self, chunk_id: str) -> str:
        return str(self._uuid.uuid5(self._uuid.NAMESPACE_DNS, chunk_id))

    def upsert(self, chunks: list[ChunkResult]) -> None:
        from qdrant_client.models import PointStruct

        if not chunks:
            return
        for chunk in chunks:
            if len(chunk.embedding) != settings.EMBEDDING_DIM:
                raise ValueError(
                    f"Embedding dimension mismatch for chunk_id={chunk.chunk_id}: "
                    f"expected {settings.EMBEDDING_DIM}, got {len(chunk.embedding)}"
                )
        points = [
            PointStruct(
                id=self._point_id(chunk.chunk_id),
                vector=chunk.embedding,
                payload={
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "content": chunk.content,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "section": chunk.section,
                    **chunk.metadata,
                },
            )
            for chunk in chunks
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[ChunkResult]:
        query_filter = None
        if filters and filters.get("doc_id"):
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            query_filter = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=filters["doc_id"]))]
            )
        response = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )
        chunks: list[ChunkResult] = []
        for hit in response.points:
            payload = dict(hit.payload or {})
            chunk_id = payload.pop("chunk_id")
            doc_id = payload.pop("doc_id")
            content = payload.pop("content", "")
            page_start = payload.pop("page_start", None)
            page_end = payload.pop("page_end", None)
            section = payload.pop("section", None)
            payload["score"] = hit.score
            chunks.append(ChunkResult(
                chunk_id=chunk_id,
                doc_id=doc_id,
                content=content,
                embedding=[],
                page_start=page_start,
                page_end=page_end,
                section=section,
                metadata=payload,
            ))
        return chunks

    def delete(self, doc_id: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._chunks: dict[str, ChunkResult] = {}

    def upsert(self, chunks: list[ChunkResult]) -> None:
        for chunk in chunks:
            self._chunks[chunk.chunk_id] = chunk

    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[ChunkResult]:
        scored = []
        for chunk in self._chunks.values():
            if filters and filters.get("doc_id") and chunk.doc_id != filters["doc_id"]:
                continue
            score = _cosine_similarity(vector, chunk.embedding)
            merged = chunk.model_copy(deep=True)
            merged.metadata["score"] = score
            scored.append(merged)
        scored.sort(key=lambda item: item.metadata.get("score", 0), reverse=True)
        return scored[:top_k]

    def delete(self, doc_id: str) -> None:
        to_remove = [cid for cid, c in self._chunks.items() if c.doc_id == doc_id]
        for cid in to_remove:
            del self._chunks[cid]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


# ─── Metadata store implementations ──────────────────────────────────────────

class SQLMetadataStore:
    def __init__(self, db_url: str | None = None) -> None:
        from sqlalchemy import create_engine
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

    def upsert(self, doc: DocumentRecord) -> None:
        payload = doc.model_dump()
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
        return DocumentRecord(**dict(row)) if row else None

    def get_by_file_path(self, file_path: str) -> DocumentRecord | None:
        from sqlalchemy import select

        with self._engine.begin() as conn:
            row = conn.execute(
                select(self._documents).where(self._documents.c.file_path == file_path)
            ).mappings().first()
        return DocumentRecord(**dict(row)) if row else None

    def get_by_file_paths(self, file_paths: list[str]) -> dict[str, DocumentRecord]:
        from sqlalchemy import select

        if not file_paths:
            return {}
        with self._engine.begin() as conn:
            rows = conn.execute(
                select(self._documents).where(self._documents.c.file_path.in_(file_paths))
            ).mappings().all()
        return {row["file_path"]: DocumentRecord(**dict(row)) for row in rows}

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
            if existing.status == "indexing" and not _is_stale_indexing(existing):
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

    def record_job(self, doc_id: str, status: str, chunk_count: int = 0,
                   embedding_model: str = "", duration_seconds: float = 0.0,
                   error_message: str | None = None) -> None:
        import uuid

        now = datetime.now(timezone.utc)
        with self._engine.begin() as conn:
            conn.execute(self._jobs.insert().values(
                id=str(uuid.uuid4()), doc_id=doc_id, status=status,
                chunk_count=chunk_count, embedding_model=embedding_model or None,
                duration_seconds=duration_seconds, error_message=error_message,
                started_at=now, finished_at=now if status in ("indexed", "failed") else None,
            ))

    def update_processed(self, doc_id: str, total_chunks: int, processed_at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                self._documents.update()
                .where(self._documents.c.id == doc_id)
                .values(total_chunks=total_chunks, processed_at=processed_at,
                        updated_at=datetime.now(timezone.utc))
            )


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
        doc = docs.get(doc_id, {})
        doc["id"] = doc_id
        doc["status"] = status
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        docs[doc_id] = doc
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
            file_path = payload.get("file_path")
            if file_path in wanted:
                found[file_path] = DocumentRecord(**payload)
        return found

    def try_claim_ingest(self, job: IngestJob) -> bool:
        docs = self._read()
        payload = docs.get(job.doc_id)
        if payload:
            existing = DocumentRecord(**payload)
            if existing.status == "indexing" and not _is_stale_indexing(existing):
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

    def record_job(self, doc_id: str, status: str, chunk_count: int = 0,
                   embedding_model: str = "", duration_seconds: float = 0.0,
                   error_message: str | None = None) -> None:
        import json
        existing: list[dict]
        if self._jobs_file.exists():
            existing = json.loads(self._jobs_file.read_text(encoding="utf-8"))
        else:
            existing = []
        now = datetime.now(timezone.utc).isoformat()
        existing.append(
            {
                "doc_id": doc_id,
                "status": status,
                "chunk_count": chunk_count,
                "embedding_model": embedding_model or None,
                "duration_seconds": duration_seconds,
                "error_message": error_message,
                "started_at": now,
                "finished_at": now if status in {"indexed", "failed"} else None,
            }
        )
        self._jobs_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def update_processed(self, doc_id: str, total_chunks: int, processed_at: datetime) -> None:
        docs = self._read()
        payload = docs.get(doc_id)
        if not payload:
            return
        doc = DocumentRecord(**payload).model_copy(
            update={
                "total_chunks": total_chunks,
                "processed_at": processed_at,
                "updated_at": datetime.now(timezone.utc),
            }
        )
        docs[doc_id] = doc.model_dump(mode="json")
        self._write(docs)


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
        if existing and existing.status == "indexing" and not _is_stale_indexing(existing):
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

    def record_job(self, doc_id: str, status: str, chunk_count: int = 0,
                   embedding_model: str = "", duration_seconds: float = 0.0,
                   error_message: str | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._jobs.append(
            {
                "doc_id": doc_id,
                "status": status,
                "chunk_count": chunk_count,
                "embedding_model": embedding_model or None,
                "duration_seconds": duration_seconds,
                "error_message": error_message,
                "started_at": now,
                "finished_at": now if status in {"indexed", "failed"} else None,
            }
        )

    def update_processed(self, doc_id: str, total_chunks: int, processed_at: datetime) -> None:
        existing = self._documents.get(doc_id)
        if existing is None:
            return
        self._documents[doc_id] = existing.model_copy(
            update={
                "total_chunks": total_chunks,
                "processed_at": processed_at,
                "updated_at": datetime.now(timezone.utc),
            }
        )


def build_vector_store() -> tuple[VectorStore, str | None]:
    if settings.VECTOR_STORE == "memory":
        return InMemoryVectorStore(), None
    try:
        return QdrantStore(), None
    except Exception as exc:
        warning = f"QdrantStore unavailable: {exc}"
        log.warning("%s; falling back to InMemoryVectorStore", warning)
        return InMemoryVectorStore(), warning


def build_metadata_store() -> tuple[MetadataStore, str | None]:
    if settings.METADATA_STORE == "memory":
        return InMemoryMetadataStore(), None
    if settings.METADATA_STORE == "file":
        return FileMetadataStore(), None
    try:
        return SQLMetadataStore(), None
    except Exception as exc:
        warning = f"SQLMetadataStore unavailable: {exc}"
        log.warning("%s; falling back to FileMetadataStore", warning)
        return FileMetadataStore(), warning
