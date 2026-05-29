from __future__ import annotations

from config import settings
from models.ingest_job import ChunkResult
from utils.ai_provider import AIProvider


def run(chunks: list[ChunkResult], ai_provider: AIProvider, batch_size: int = 32) -> list[ChunkResult]:
    if not chunks:
        return []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        embeddings = ai_provider.embed([chunk.content for chunk in batch])
        if len(embeddings) != len(batch):
            raise ValueError(
                f"Embedding response size mismatch: expected {len(batch)}, got {len(embeddings)}"
            )
        for chunk, embedding in zip(batch, embeddings):
            if len(embedding) != settings.EMBEDDING_DIM:
                raise ValueError(
                    f"Embedding dimension mismatch for chunk_id={chunk.chunk_id}: "
                    f"expected {settings.EMBEDDING_DIM}, got {len(embedding)}"
                )
            chunk.embedding = embedding
            chunk.metadata["embedding_model"] = settings.EMBED_MODEL
    return chunks
