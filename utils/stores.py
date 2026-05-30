"""
utils/stores — backward-compat re-export layer.

New code should import implementations directly from app/infrastructure/.
This module exists so existing tests and legacy entrypoints continue to work
without modification during the migration period.
"""
from __future__ import annotations

import logging
from abc import abstractmethod
from typing import Protocol

from app.domain.documents.models import DocumentRecord, IngestJob
from app.domain.ingestion.policies import is_stale_indexing as _is_stale_indexing_domain
from app.infrastructure.repositories.file_metadata_store import FileMetadataStore
from app.infrastructure.repositories.memory_metadata_store import InMemoryMetadataStore
from app.infrastructure.repositories.sql_metadata_store import SQLMetadataStore
from app.infrastructure.vector.memory_store import InMemoryVectorStore, _cosine_similarity
from app.infrastructure.vector.qdrant_store import QdrantStore
from config import settings
from models.ingest_job import ChunkResult

log = logging.getLogger(__name__)


# ─── Internal helper (kept for backward compat; delegates to domain policy) ──

def _is_stale_indexing(doc: DocumentRecord) -> bool:
    return _is_stale_indexing_domain(doc, settings.STALE_INDEXING_SECONDS)


# ─── Protocols ────────────────────────────────────────────────────────────────

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
        processed_at,
    ) -> None: ...


# ─── Factory functions ────────────────────────────────────────────────────────

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


__all__ = [
    "VectorStore",
    "MetadataStore",
    "QdrantStore",
    "InMemoryVectorStore",
    "SQLMetadataStore",
    "FileMetadataStore",
    "InMemoryMetadataStore",
    "_cosine_similarity",
    "_is_stale_indexing",
    "build_vector_store",
    "build_metadata_store",
]
