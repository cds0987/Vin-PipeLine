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
    deadline_monotonic: float | None = None,
) -> dict:
    def _check_deadline(stage: str) -> None:
        if deadline_monotonic is not None and time.perf_counter() > deadline_monotonic:
            raise TimeoutError(f"doc_id={job.doc_id}: ingest timeout exceeded at stage={stage}")

    started_at = time.perf_counter()
    ai = ai_provider or build_ai_provider()
    vectors = vector_store or build_vector_store()
    metadata = metadata_store or build_metadata_store()
    try:
        if not metadata.try_claim_ingest(job):
            return {"doc_id": job.doc_id, "status": "skipped", "chunk_count": 0}
        _check_deadline("parse")
        pages = parse.run(job, ai)
        _check_deadline("clean")
        pages = clean.run(pages)
        _check_deadline("chunk")
        chunks = chunk.run(pages, job)
        if not chunks:
            raise ValueError(f"doc_id={job.doc_id}: parse produced empty text - possible scan PDF without OCR")
        _check_deadline("embed")
        chunks = embed.run(chunks, ai)
        _check_deadline("index")
        duration = round(time.perf_counter() - started_at, 3)
        stats = index.run(
            chunks,
            job,
            vectors,
            metadata,
            embedding_model=settings.EMBED_MODEL,
            duration_seconds=duration,
        )
        stats["embedding_model"] = settings.EMBED_MODEL
        stats["duration_seconds"] = duration
        return stats
    except Exception as exc:
        duration = round(time.perf_counter() - started_at, 3)
        metadata.record_job(
            doc_id=job.doc_id,
            status="failed",
            duration_seconds=duration,
            error_message=str(exc),
        )
        metadata.update_status(job.doc_id, "failed")
        raise
