from __future__ import annotations

from app.domain.documents.models import SectionRecord
from config import settings
from utils.ai_provider import AIProvider


class AISectionEmbedder:
    def __init__(self, ai_provider: AIProvider) -> None:
        self._ai_provider = ai_provider

    def embed_sections(self, sections: list[SectionRecord], batch_size: int = 32) -> list[SectionRecord]:
        if not sections:
            return []
        for start in range(0, len(sections), batch_size):
            batch = sections[start : start + batch_size]
            embeddings = self._ai_provider.embed([section.caption for section in batch])
            if len(embeddings) != len(batch):
                raise ValueError(
                    f"Embedding response size mismatch: expected {len(batch)}, got {len(embeddings)}"
                )
            for section, embedding in zip(batch, embeddings):
                if len(embedding) != settings.EMBEDDING_DIM:
                    raise ValueError(
                        f"Embedding dimension mismatch for section_id={section.section_id}: "
                        f"expected {settings.EMBEDDING_DIM}, got {len(embedding)}"
                    )
                section.embedding = embedding
                section.metadata["embedding_model"] = settings.EMBED_MODEL
        return sections
