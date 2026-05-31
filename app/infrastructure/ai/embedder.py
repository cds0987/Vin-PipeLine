from __future__ import annotations

from app.domain.documents.models import SectionRecord
from config import settings
from utils.batch_embedder import BatchEmbedder


class AISectionEmbedder:
    def __init__(self, batch_embedder: BatchEmbedder) -> None:
        self._batch_embedder = batch_embedder

    async def embed_sections(self, sections: list[SectionRecord], batch_size: int = 32) -> list[SectionRecord]:
        if not sections:
            return []

        captions = [section.caption for section in sections]
        embeddings = await self._batch_embedder.embed_batch(captions)

        if len(embeddings) != len(sections):
            raise ValueError(
                f"Embedding response size mismatch: expected {len(sections)}, got {len(embeddings)}"
            )

        for section, embedding in zip(sections, embeddings):
            if len(embedding) != settings.EMBEDDING_DIM:
                raise ValueError(
                    f"Embedding dimension mismatch for section_id={section.section_id}: "
                    f"expected {settings.EMBEDDING_DIM}, got {len(embedding)}"
                )
            section.embedding = embedding
            section.metadata["embedding_model"] = settings.EMBED_MODEL

        return sections
