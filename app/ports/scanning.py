from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from app.domain.documents.models import IngestJob


class SourceScanner(Protocol):
    @abstractmethod
    def scan(self, bucket: str | None = None, prefix: str | None = None) -> list[IngestJob]: ...
