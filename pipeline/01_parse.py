from __future__ import annotations

from app.infrastructure.parser.router import RouterDocumentParser
from models.ingest_job import IngestJob
from utils.ai_provider import AIProvider


def run(job: IngestJob, ai_provider: AIProvider, file_bytes: bytes) -> list[tuple[int, str]]:
    parser = RouterDocumentParser(ai_provider)
    markdown = parser.parse(job, file_bytes)
    return [(1, markdown.markdown_content)] if markdown.markdown_content.strip() else []
