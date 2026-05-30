from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from app.domain.markdown.models import MarkdownDocument


class MarkdownStore(Protocol):
    """Persist and retrieve Markdown artifacts."""

    @abstractmethod
    def save(self, document: MarkdownDocument) -> MarkdownDocument: ...

    @abstractmethod
    def read(self, markdown_uri: str) -> str: ...
