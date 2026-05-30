from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from app.domain.documents.models import IngestJob
from app.domain.markdown.models import MarkdownDocument


class DocumentParser(Protocol):
    """Convert raw file bytes into a MarkdownDocument."""

    @abstractmethod
    def parse(self, job: IngestJob, file_bytes: bytes) -> MarkdownDocument: ...
