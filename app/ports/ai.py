# Re-exports for backward compatibility.
# Canonical location for EmbeddingProvider: embedding_provider.py
from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Protocol

from app.ports.embedding_provider import EmbeddingProvider

if TYPE_CHECKING:
    from app.domain.sections.models import SectionRecord


class SectionEmbedder(Protocol):
    """Embed captions for a batch of sections, attaching vectors in-place."""

    @abstractmethod
    def embed_sections(self, sections: list["SectionRecord"]) -> list["SectionRecord"]: ...


class CaptionProvider(Protocol):
    @abstractmethod
    def caption(self, texts: list[str]) -> list[str]: ...


class OCRProvider(Protocol):
    @abstractmethod
    def ocr(self, image_bytes: bytes) -> str: ...


class LLMClientProvider(Protocol):
    @abstractmethod
    def get_llm_client(self) -> Any | None: ...


__all__ = [
    "EmbeddingProvider",
    "SectionEmbedder",
    "CaptionProvider",
    "OCRProvider",
    "LLMClientProvider",
]
