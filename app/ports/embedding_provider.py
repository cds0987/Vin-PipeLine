from __future__ import annotations

from abc import abstractmethod
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Convert a list of text strings into embedding vectors."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...
