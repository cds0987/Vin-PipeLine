from __future__ import annotations

import importlib
import time

from config import settings
from models.ingest_job import IngestJob
from utils.ai_provider import AIProvider, build_ai_provider
from utils.notifier import notify_indexing_done, notify_indexing_failed
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
        chunks = embed.run(chunks, ai)
        stats = index.run(chunks, job, vectors, metadata)
        stats["embedding_model"] = settings.EMBED_MODEL
        stats["duration_seconds"] = round(time.perf_counter() - started_at, 3)
        notify_indexing_done(job.doc_id, stats["chunk_count"])
        return stats
    except Exception as exc:
        notify_indexing_failed(job.doc_id, str(exc))
        raise
