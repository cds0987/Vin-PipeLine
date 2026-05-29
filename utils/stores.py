from __future__ import annotations

import logging
from abc import abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from config import settings
from models.ingest_job import ChunkResult, DocumentRecord, PermissionModel

log = logging.getLogger(__name__)


class VectorStore(Protocol):
    @abstractmethod
    def upsert(self, chunks: list[ChunkResult]) -> None:
        ...

    @abstractmethod
    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[ChunkResult]:
        ...

    @abstractmethod
    def delete(self, doc_id: str) -> None:
        ...


class MetadataStore(Protocol):
    @abstractmethod
    def upsert(self, doc: DocumentRecord) -> None:
        ...

    @abstractmethod
    def update_status(self, doc_id: str, status: str) -> None:
        ...

    @abstractmethod
    def upsert_permission(self, doc_id: str, permission: PermissionModel) -> None:
        ...

    @abstractmethod
    def get_permission(self, doc_id: str) -> PermissionModel | None:
        ...


class QdrantStore:
    def __init__(self) -> None:
        import uuid as _uuid
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

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
        hits = self._client.search(
            collection_name=self._collection,
            query_vector=vector,
            limit=top_k,
            with_payload=True,
            with_vectors=False,
        )
        chunks: list[ChunkResult] = []
        for hit in hits:
            payload = dict(hit.payload or {})
            chunk_id = payload.pop("chunk_id")
            doc_id = payload.pop("doc_id")
            content = payload.pop("content", "")
            page_start = payload.pop("page_start", None)
            page_end = payload.pop("page_end", None)
            section = payload.pop("section", None)
            payload["score"] = hit.score
            chunks.append(
                ChunkResult(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    content=content,
                    embedding=[],
                    page_start=page_start,
                    page_end=page_end,
                    section=section,
                    metadata=payload,
                )
            )
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
        for chunk_id in [chunk_id for chunk_id, chunk in self._chunks.items() if chunk.doc_id == doc_id]:
            del self._chunks[chunk_id]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class SQLMetadataStore:
    def __init__(self, db_url: str | None = None) -> None:
        from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, create_engine
        from sqlalchemy.dialects.postgresql import JSONB

        self._engine = create_engine(db_url or settings.DB_URL, future=True)
        self._metadata = MetaData()
        json_type = JSONB if self._engine.dialect.name == "postgresql" else JSON
        self._documents = Table(
            "documents",
            self._metadata,
            Column("doc_id", String, primary_key=True),
            Column("file_uri", String, nullable=False),
            Column("file_name", String),
            Column("document_type", String, nullable=False),
            Column("language", String, nullable=False),
            Column("status", String, nullable=False),
            Column("uploaded_by", String),
            Column("org_id", String),
            Column("created_at", DateTime, nullable=False),
            Column("updated_at", DateTime, nullable=False),
        )
        self._permissions = Table(
            "document_permissions",
            self._metadata,
            Column("doc_id", String, primary_key=True),
            Column("visibility", String, nullable=False),
            Column("owner_id", String),
            Column("org_id", String),
            Column("allowed_roles", json_type, nullable=False),
            Column("allowed_users", json_type, nullable=False),
            Column("updated_at", DateTime, nullable=False),
        )
        self._metadata.create_all(self._engine)

    def upsert(self, doc: DocumentRecord) -> None:
        from sqlalchemy import delete

        payload = doc.model_dump()
        with self._engine.begin() as conn:
            conn.execute(delete(self._documents).where(self._documents.c.doc_id == doc.doc_id))
            conn.execute(self._documents.insert().values(**payload))

    def update_status(self, doc_id: str, status: str) -> None:
        from sqlalchemy import select

        with self._engine.begin() as conn:
            row = conn.execute(select(self._documents).where(self._documents.c.doc_id == doc_id)).mappings().first()
            if row is None:
                conn.execute(
                    self._documents.insert().values(
                        doc_id=doc_id,
                        file_uri="",
                        file_name=None,
                        document_type="general",
                        language="vi",
                        status=status,
                        uploaded_by=None,
                        org_id=None,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
                return
            conn.execute(
                self._documents.update()
                .where(self._documents.c.doc_id == doc_id)
                .values(status=status, updated_at=datetime.now(timezone.utc))
                )

    def upsert_permission(self, doc_id: str, permission: PermissionModel) -> None:
        from sqlalchemy import delete

        payload = permission.model_dump()
        payload["doc_id"] = doc_id
        payload["updated_at"] = datetime.now(timezone.utc)
        with self._engine.begin() as conn:
            conn.execute(delete(self._permissions).where(self._permissions.c.doc_id == doc_id))
            conn.execute(self._permissions.insert().values(**payload))

    def get_permission(self, doc_id: str) -> PermissionModel | None:
        from sqlalchemy import select

        with self._engine.begin() as conn:
            row = conn.execute(select(self._permissions).where(self._permissions.c.doc_id == doc_id)).mappings().first()
        if row is None:
            return None
        return PermissionModel(
            visibility=row["visibility"],
            owner_id=row["owner_id"],
            org_id=row["org_id"],
            allowed_roles=list(row["allowed_roles"] or []),
            allowed_users=list(row["allowed_users"] or []),
        )


class FileMetadataStore:
    def __init__(self, base_dir: str | None = None) -> None:
        self._base_dir = Path(base_dir or "data/local_store")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._documents_file = self._base_dir / "documents.json"
        self._permissions_file = self._base_dir / "permissions.json"

    def _read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        import json

        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict) -> None:
        import json

        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def upsert(self, doc: DocumentRecord) -> None:
        docs = self._read_json(self._documents_file)
        docs[doc.doc_id] = doc.model_dump(mode="json")
        self._write_json(self._documents_file, docs)

    def update_status(self, doc_id: str, status: str) -> None:
        docs = self._read_json(self._documents_file)
        doc = docs.get(doc_id, {})
        doc["doc_id"] = doc_id
        doc["status"] = status
        doc["updated_at"] = datetime.now(timezone.utc).isoformat()
        docs[doc_id] = doc
        self._write_json(self._documents_file, docs)

    def upsert_permission(self, doc_id: str, permission: PermissionModel) -> None:
        permissions = self._read_json(self._permissions_file)
        permissions[doc_id] = permission.model_dump(mode="json")
        self._write_json(self._permissions_file, permissions)

    def get_permission(self, doc_id: str) -> PermissionModel | None:
        permissions = self._read_json(self._permissions_file)
        payload = permissions.get(doc_id)
        return PermissionModel(**payload) if payload else None


class InMemoryMetadataStore:
    def __init__(self) -> None:
        self._documents: dict[str, DocumentRecord] = {}
        self._permissions: dict[str, PermissionModel] = {}

    def upsert(self, doc: DocumentRecord) -> None:
        self._documents[doc.doc_id] = doc

    def update_status(self, doc_id: str, status: str) -> None:
        if doc_id in self._documents:
            self._documents[doc_id] = self._documents[doc_id].model_copy(update={"status": status})
        else:
            self._documents[doc_id] = DocumentRecord(doc_id=doc_id, file_uri="", status=status)

    def upsert_permission(self, doc_id: str, permission: PermissionModel) -> None:
        self._permissions[doc_id] = permission

    def get_permission(self, doc_id: str) -> PermissionModel | None:
        return self._permissions.get(doc_id)


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
