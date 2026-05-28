from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Protocol

from config import settings
from models.ingest_job import ChunkResult, DocumentRecord, PermissionModel


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


class ChromaStore:
    def __init__(self) -> None:
        import chromadb

        host = settings.CHROMA_HOST
        port = settings.CHROMA_PORT
        if host:
            try:
                self._client = chromadb.HttpClient(host=host, port=port)
                self._client.heartbeat()
            except Exception:
                self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        else:
            self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        self._collection = self._client.get_or_create_collection(name=settings.CHROMA_COLLECTION)

    def upsert(self, chunks: list[ChunkResult]) -> None:
        if not chunks:
            return
        self._collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.content for chunk in chunks],
            embeddings=[chunk.embedding for chunk in chunks],
            metadatas=[
                {
                    "doc_id": chunk.doc_id,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "section": chunk.section,
                    **chunk.metadata,
                }
                for chunk in chunks
            ],
        )

    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[ChunkResult]:
        result = self._collection.query(query_embeddings=[vector], n_results=top_k)
        chunks: list[ChunkResult] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for idx, chunk_id in enumerate(ids):
            metadata = dict(metas[idx] or {})
            metadata["score"] = 1 - distances[idx] if idx < len(distances) else None
            doc_id = metadata.pop("doc_id")
            chunks.append(
                ChunkResult(
                    chunk_id=chunk_id,
                    doc_id=doc_id,
                    content=docs[idx],
                    embedding=[],
                    page_start=metadata.pop("page_start", None),
                    page_end=metadata.pop("page_end", None),
                    section=metadata.pop("section", None),
                    metadata=metadata,
                )
            )
        return chunks

    def delete(self, doc_id: str) -> None:
        self._collection.delete(where={"doc_id": doc_id})


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
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                )
                return
            conn.execute(
                self._documents.update()
                .where(self._documents.c.doc_id == doc_id)
                .values(status=status, updated_at=datetime.utcnow())
                )

    def upsert_permission(self, doc_id: str, permission: PermissionModel) -> None:
        from sqlalchemy import delete

        payload = permission.model_dump()
        payload["doc_id"] = doc_id
        payload["updated_at"] = datetime.utcnow()
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
        doc["updated_at"] = datetime.utcnow().isoformat()
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


def build_vector_store() -> VectorStore:
    if settings.VECTOR_STORE == "memory":
        return InMemoryVectorStore()
    try:
        return ChromaStore()
    except Exception:
        return InMemoryVectorStore()


def build_metadata_store() -> MetadataStore:
    if settings.METADATA_STORE == "memory":
        return FileMetadataStore()
    try:
        return SQLMetadataStore()
    except Exception:
        return FileMetadataStore()
