from __future__ import annotations

from app.infrastructure.ai.captioner import AISectionCaptioner
from app.infrastructure.ai.embedder import AISectionEmbedder
from models.ingest_job import ChunkResult
from utils.ai_provider import AIProvider


def run(chunks: list[ChunkResult], ai_provider: AIProvider, batch_size: int = 32) -> list[ChunkResult]:
    sections = AISectionCaptioner(ai_provider).caption_sections(chunks)
    return AISectionEmbedder(ai_provider).embed_sections(sections, batch_size=batch_size)
