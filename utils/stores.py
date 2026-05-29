from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from config import settings
from models.ingest_job import ChunkResult, DocumentRecord

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
    def upsert_chunks(self, chunks: list[ChunkResult]) -> None: ...

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
        response = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=top_k,
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
        from db.schema import document_chunks, documents, ingestion_jobs, metadata as schema_metadata

        self._engine = create_engine(db_url or settings.DB_URL, future=True)
        self._metadata = schema_metadata
        self._documents = documents
        self._chunks = document_chunks
        self._jobs = ingestion_jobs
        self._metadata.create_all(self._engine)

    def upsert(self, doc: DocumentRecord) -> None:
        from sqlalchemy import delete

        payload = doc.model_dump()
        with self._engine.begin() as conn:
            conn.execute(delete(self._documents).where(self._documents.c.id == doc.id))
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

    def upsert_chunks(self, chunks: list[ChunkResult]) -> None:
        from sqlalchemy import delete

        if not chunks:
            return
        doc_id = chunks[0].doc_id
        now = datetime.now(timezone.utc)
        rows = [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "chunk_index": c.metadata.get("chunk_index", i),
                "content": c.content,
                "page_start": c.page_start,
                "page_end": c.page_end,
                "section": c.section,
                "token_count": (c.metadata.get("token_end", 0) - c.metadata.get("token_start", 0)) or None,
                "created_at": now,
            }
            for i, c in enumerate(chunks)
        ]
        with self._engine.begin() as conn:
            conn.execute(delete(self._chunks).where(self._chunks.c.doc_id == doc_id))
            conn.execute(self._chunks.insert(), rows)

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

    def upsert_chunks(self, chunks: list[ChunkResult]) -> None:
        pass

    def record_job(self, doc_id: str, status: str, chunk_count: int = 0,
                   embedding_model: str = "", duration_seconds: float = 0.0,
                   error_message: str | None = None) -> None:
        pass


class InMemoryMetadataStore:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}

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

    def upsert_chunks(self, chunks: list[ChunkResult]) -> None:
        pass

    def record_job(self, doc_id: str, status: str, chunk_count: int = 0,
                   embedding_model: str = "", duration_seconds: float = 0.0,
                   error_message: str | None = None) -> None:
        pass


def build_vector_store() -> VectorStore:
    if settings.VECTOR_STORE == "memory":
        return InMemoryVectorStore()
    try:
        return QdrantStore()
    except Exception as exc:
        log.warning("QdrantStore unavailable (%s), falling back to InMemoryVectorStore", exc)
        return InMemoryVectorStore()


def build_metadata_store() -> MetadataStore:
    if settings.METADATA_STORE == "memory":
        return InMemoryMetadataStore()
    if settings.METADATA_STORE == "file":
        return FileMetadataStore()
    try:
        return SQLMetadataStore()
    except Exception as exc:
        log.warning("SQLMetadataStore unavailable (%s), falling back to FileMetadataStore", exc)
        return FileMetadataStore()
