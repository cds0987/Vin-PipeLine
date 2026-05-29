from __future__ import annotations

import importlib
import time

from config import settings
from models.ingest_job import IngestJob
from utils.ai_provider import AIProvider, build_ai_provider
from utils.stores import MetadataStore, VectorStore, build_metadata_store, build_vector_store

parse = importlib.import_module("pipeline.01_parse")
clean = importlib.import_module("pipeline.02_clean")
chunk = importlib.import_module("pipeline.03_chunk")
embed = importlib.import_module("pipeline.04_embed")
index = importlib.import_module("pipeline.05_index")


def run(
    job: IngestJob,
    ai_provider: AIProvider | None = None,
    vector_store: VectorStore | None = None,
    metadata_store: MetadataStore | None = None,
) -> dict:
    started_at = time.perf_counter()
    ai = ai_provider or build_ai_provider()
    vectors = vector_store or build_vector_store()
    metadata = metadata_store or build_metadata_store()
    try:
        text = parse.run(job, ai)
        text = clean.run(text)
        chunks = chunk.run(text, job)
        if not chunks:
            raise ValueError(f"doc_id={job.doc_id}: parse produced empty text — possible scan PDF without OCR")
        chunks = embed.run(chunks, ai)
        duration = round(time.perf_counter() - started_at, 3)
        stats = index.run(chunks, job, vectors, metadata,
                          embedding_model=settings.EMBED_MODEL,
                          duration_seconds=duration)
        stats["embedding_model"] = settings.EMBED_MODEL
        stats["duration_seconds"] = duration
        return stats
    except Exception as exc:
        duration = round(time.perf_counter() - started_at, 3)
        metadata.record_job(doc_id=job.doc_id, status="failed",
                            duration_seconds=duration, error_message=str(exc))
        metadata.update_status(job.doc_id, "failed")
        raise
