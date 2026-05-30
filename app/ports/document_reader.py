from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class DocumentReader(Protocol):
    """Read raw bytes of a source document from any URI (S3, local, etc.)."""

    @abstractmethod
    def read(self, file_uri: str) -> bytes: ...
