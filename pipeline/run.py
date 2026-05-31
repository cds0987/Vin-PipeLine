from __future__ import annotations

import asyncio

from app.bootstrap.container import build_container
from models.ingest_job import IngestJob
from utils.ai_provider import AIProvider
from utils.stores import MetadataStore, VectorStore


def run(
    job: IngestJob,
    ai_provider: AIProvider | None = None,
    vector_store: VectorStore | None = None,
    metadata_store: MetadataStore | None = None,
    deadline_monotonic: float | None = None,
) -> dict:
    container = build_container(
        ai_provider=ai_provider,
        vector_store=vector_store,
        metadata_store=metadata_store,
    )
    return asyncio.run(container.run_ingest_job.execute(job, deadline_monotonic=deadline_monotonic))
