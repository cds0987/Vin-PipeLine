from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel, Field

from config import settings
from pipeline.run import run as run_pipeline
from retrieval.service import RetrievalService
from utils.ai_provider import build_ai_provider
from utils.stores import MetadataStore, VectorStore, build_metadata_store, build_vector_store

log = logging.getLogger(__name__)

# Prevents concurrent scan+ingest cycles across the background scanner and manual /scan.
_scan_lock = threading.Lock()


class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)


class ScanRequest(BaseModel):
    bucket: str | None = None
    prefix: str | None = None


def _run_single_job(job, ai_provider, vector_store: VectorStore, metadata_store: MetadataStore) -> dict:
    deadline_monotonic = None
    if settings.SCAN_JOB_TIMEOUT_SECONDS > 0:
        deadline_monotonic = time.perf_counter() + settings.SCAN_JOB_TIMEOUT_SECONDS
    return run_pipeline(
        job,
        ai_provider=ai_provider,
        vector_store=vector_store,
        metadata_store=metadata_store,
        deadline_monotonic=deadline_monotonic,
    )


def _run_jobs(jobs, ai_provider, vector_store: VectorStore, metadata_store: MetadataStore) -> int:
    """Run a pre-computed job list while the scan lock is already held."""
    ran = 0
    if not jobs:
        return ran

    with ThreadPoolExecutor(max_workers=settings.SCAN_MAX_WORKERS) as pool:
        futures = {
            pool.submit(
                _run_single_job,
                job,
                ai_provider,
                vector_store,
                metadata_store,
            ): job
            for job in jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                future.result()
                ran += 1
            except Exception as exc:
                log.error("Pipeline failed doc_id=%s: %s", job.doc_id, exc)
    return ran


def _run_jobs_and_release_lock(jobs, ai_provider, vector_store: VectorStore, metadata_store: MetadataStore) -> int:
    try:
        return _run_jobs(jobs, ai_provider, vector_store, metadata_store)
    finally:
        _scan_lock.release()


def _scan_and_run_once(ai_provider, vector_store: VectorStore, metadata_store: MetadataStore) -> int:
    from adapters.s3_adapter import S3Scanner

    if not _scan_lock.acquire(blocking=False):
        log.warning("Scan already in progress - skipping scanner cycle")
        return 0

    try:
        jobs = S3Scanner(metadata_store).scan()
        return _run_jobs(jobs, ai_provider, vector_store, metadata_store)
    finally:
        _scan_lock.release()


def _scanner_loop(ai_provider, vector_store: VectorStore, metadata_store: MetadataStore) -> None:
    """Poll S3 every SCAN_INTERVAL_SECONDS and skip a cycle if one is still running."""
    interval = settings.SCAN_INTERVAL_SECONDS
    log.info(
        "S3 scanner started - interval=%ds bucket=%s prefix=%r",
        interval,
        settings.S3_BUCKET,
        settings.SCAN_PREFIX,
    )

    while True:
        try:
            _scan_and_run_once(ai_provider, vector_store, metadata_store)
        except Exception as exc:
            log.error("Scanner loop error: %s", exc)
        time.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ai_provider = build_ai_provider()
    app.state.vector_store = build_vector_store()
    app.state.metadata_store = build_metadata_store()
    app.state.retrieval_service = RetrievalService(
        ai_provider=app.state.ai_provider,
        vector_store=app.state.vector_store,
    )

    if settings.USE_S3 and settings.SCAN_INTERVAL_SECONDS > 0:
        thread = threading.Thread(
            target=_scanner_loop,
            args=(app.state.ai_provider, app.state.vector_store, app.state.metadata_store),
            daemon=True,
        )
        thread.start()
        log.info("Background S3 scanner thread started")

    yield


app = FastAPI(title="DE Vector Search Engine", lifespan=lifespan)


@app.post("/search")
def search(request: SearchRequest):
    results = app.state.retrieval_service.search(request.query, top_k=request.top_k)
    return {"request_id": str(uuid4()), "results": results}


@app.post("/scan")
def trigger_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    """Trigger a manual S3 scan and queue ingestion in the background."""
    from adapters.s3_adapter import S3Scanner

    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="scan already in progress")

    try:
        jobs = S3Scanner(app.state.metadata_store).scan(
            bucket=request.bucket,
            prefix=request.prefix,
        )
    except Exception:
        _scan_lock.release()
        raise

    if not jobs:
        _scan_lock.release()
        return {"status": "scan started", "queued": 0}

    background_tasks.add_task(
        _run_jobs_and_release_lock,
        jobs,
        app.state.ai_provider,
        app.state.vector_store,
        app.state.metadata_store,
    )
    return {"status": "scan started", "queued": len(jobs)}


@app.get("/status/{doc_id}")
def get_status(doc_id: str):
    doc = app.state.metadata_store.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"doc_id={doc_id} not found")
    return {
        "doc_id": doc_id,
        "status": doc.status,
        "file_path": doc.file_path,
        "file_type": doc.file_type,
        "total_chunks": doc.total_chunks,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "processed_at": doc.processed_at.isoformat() if doc.processed_at else None,
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "vector_store": settings.VECTOR_STORE,
        "ai_provider": app.state.ai_provider.__class__.__name__,
        "scanner": "enabled" if (settings.USE_S3 and settings.SCAN_INTERVAL_SECONDS > 0) else "disabled",
    }
