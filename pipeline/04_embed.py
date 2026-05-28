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
        for chunk, embedding in zip(batch, embeddings):
            chunk.embedding = embedding
            chunk.metadata["embedding_model"] = settings.EMBED_MODEL
    return chunks
