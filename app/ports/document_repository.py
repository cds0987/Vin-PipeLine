from __future__ import annotations

from abc import abstractmethod
from datetime import datetime
from typing import Protocol

from app.domain.documents.models import DocumentRecord


class DocumentRepository(Protocol):
    """CRUD operations for document metadata."""

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
    def update_processed(self, doc_id: str, section_count: int, processed_at: datetime) -> None: ...
