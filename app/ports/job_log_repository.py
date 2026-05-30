from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class JobLogRepository(Protocol):
    """Append-only log of ingest job outcomes."""

    @abstractmethod
    def record_job(
        self,
        doc_id: str,
        status: str,
        section_count: int = 0,
        embedding_model: str = "",
        duration_seconds: float = 0.0,
        error_message: str | None = None,
    ) -> None: ...
