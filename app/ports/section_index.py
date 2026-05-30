from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from app.domain.sections.models import SectionRecord


class SectionIndex(Protocol):
    """Write and search section records in the vector store."""

    @abstractmethod
    def upsert_sections(self, sections: list[SectionRecord]) -> None: ...

    @abstractmethod
    def search_sections(self, vector: list[float], top_k: int) -> list[SectionRecord]: ...

    @abstractmethod
    def delete_document(self, doc_id: str) -> None: ...
