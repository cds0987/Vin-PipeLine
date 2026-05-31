from __future__ import annotations

import asyncio

from app.infrastructure.ai.captioner import AISectionCaptioner
from app.infrastructure.ai.embedder import AISectionEmbedder
from config import settings
from models.ingest_job import ChunkResult
from utils.ai_provider import AIProvider
from utils.batch_embedder import BatchEmbedder


def run(chunks: list[ChunkResult], ai_provider: AIProvider, batch_size: int = 32) -> list[ChunkResult]:
    async def _run_async():
        batch_embedder = BatchEmbedder(
            provider=ai_provider,
            max_batch_size=settings.EMBED_MAX_BATCH_SIZE,
            window_ms=settings.EMBED_BATCH_WINDOW_MS,
            cache_size=settings.EMBED_CACHE_SIZE,
        )
        sections = await AISectionCaptioner(ai_provider).caption_sections(chunks)
        return await AISectionEmbedder(batch_embedder).embed_sections(sections, batch_size=batch_size)

    return asyncio.run(_run_async())
