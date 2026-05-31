from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.bootstrap.container import Container, build_container
from config import settings
from models.ingest_job import IngestJob

log = logging.getLogger(__name__)

# threading.Lock so test_scan_coordination can call .acquire(blocking=False) directly
_scan_lock = threading.Lock()
_DEFAULT_JOB_QUEUE_SIZE_MULTIPLIER = 4


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.SEARCH_QUERY_MAX_LENGTH)
    top_k: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def _validate_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class ScanRequest(BaseModel):
    bucket: str | None = None
    prefix: str | None = None


class _JobDispatcher:
    """Async job dispatcher — one consumer task, semaphore-bounded workers."""

    def __init__(self, max_workers: int, queue_capacity: int) -> None:
        self._max_workers = max_workers
        self._queue: asyncio.Queue[tuple[IngestJob, Container]] = asyncio.Queue(maxsize=queue_capacity)
        self._semaphore = asyncio.Semaphore(max_workers)
        self._stop_event = asyncio.Event()
        self._queued_doc_ids: set[str] = set()
        self._running_doc_ids: set[str] = set()
        self._consumer_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._consumer_task = asyncio.create_task(self._consumer_loop(), name="job-dispatcher-consumer")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

    def enqueue_jobs(self, jobs: list[IngestJob], container: Container) -> int:
        """Sync entry point — safe to call from async endpoints without await."""
        enqueued = 0
        for job in jobs:
            if job.doc_id in self._queued_doc_ids or job.doc_id in self._running_doc_ids:
                continue
            try:
                self._queue.put_nowait((job, container))
                self._queued_doc_ids.add(job.doc_id)
                enqueued += 1
            except asyncio.QueueFull:
                log.warning("Dispatcher queue full - dropping doc_id=%s", job.doc_id)
        return enqueued

    def snapshot(self) -> dict[str, int]:
        return {
            "queue_depth": self._queue.qsize(),
            "queued_jobs": len(self._queued_doc_ids),
            "running_jobs": len(self._running_doc_ids),
        }

    async def _consumer_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                job, container = await asyncio.wait_for(self._queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            asyncio.create_task(
                self._run_job(job, container),
                name=f"ingest-{job.doc_id}",
            )
            self._queue.task_done()

    async def _run_job(self, job: IngestJob, container: Container) -> None:
        self._queued_doc_ids.discard(job.doc_id)
        self._running_doc_ids.add(job.doc_id)
        async with self._semaphore:
            try:
                deadline = None
                if settings.SCAN_JOB_TIMEOUT_SECONDS > 0:
                    deadline = time.perf_counter() + settings.SCAN_JOB_TIMEOUT_SECONDS
                await container.run_ingest_job.execute(job, deadline_monotonic=deadline)
            except Exception as exc:
                log.error("Pipeline failed doc_id=%s: %s", job.doc_id, exc)
            finally:
                self._running_doc_ids.discard(job.doc_id)


def _queue_capacity() -> int:
    return max(16, settings.SCAN_MAX_WORKERS * _DEFAULT_JOB_QUEUE_SIZE_MULTIPLIER)


async def _scan_and_enqueue_once(container: Container, dispatcher: _JobDispatcher) -> int:
    if not _scan_lock.acquire(blocking=False):
        log.warning("Scan already in progress - skipping scanner cycle")
        return 0
    try:
        jobs = await asyncio.to_thread(container.scan_documents.execute)
    finally:
        _scan_lock.release()
    return dispatcher.enqueue_jobs(jobs, container)


async def _scanner_loop(
    container: Container, dispatcher: _JobDispatcher, stop_event: asyncio.Event
) -> None:
    log.info(
        "S3 scanner started - interval=%ds bucket=%s prefix=%r",
        settings.SCAN_INTERVAL_SECONDS,
        settings.S3_BUCKET,
        settings.SCAN_PREFIX,
    )
    while True:
        try:
            await _scan_and_enqueue_once(container, dispatcher)
        except Exception as exc:
            log.error("Scanner loop error: %s", exc)
        try:
            await asyncio.wait_for(
                stop_event.wait(), timeout=settings.SCAN_INTERVAL_SECONDS
            )
            break  # stop_event was set within the interval
        except asyncio.TimeoutError:
            pass  # interval elapsed normally — continue scanning


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = build_container()
    dispatcher = _JobDispatcher(
        max_workers=settings.SCAN_MAX_WORKERS,
        queue_capacity=_queue_capacity(),
    )
    await dispatcher.start()
    app.state.container = container
    app.state.dispatcher = dispatcher

    scanner_stop = asyncio.Event()
    scanner_task = None
    if settings.USE_S3 and settings.SCAN_INTERVAL_SECONDS > 0:
        scanner_task = asyncio.create_task(
            _scanner_loop(container, dispatcher, scanner_stop),
            name="s3-scanner",
        )
        log.info("Background S3 scanner task started")

    try:
        yield
    finally:
        scanner_stop.set()
        if scanner_task:
            scanner_task.cancel()
            try:
                await scanner_task
            except asyncio.CancelledError:
                pass
        await container.batch_embedder.flush_and_close()
        await dispatcher.stop()


app = FastAPI(title="DE Vector Search Engine", lifespan=lifespan)


@app.post("/search")
async def search(request: SearchRequest):
    request_id = str(uuid4())
    results = await asyncio.to_thread(
        app.state.container.search_sections.search,
        request.query,
        top_k=request.top_k,
        request_id=request_id,
    )
    return {
        "request_id": request_id,
        "results": [result.model_dump() for result in results],
    }


@app.post("/scan")
async def trigger_scan(request: ScanRequest):
    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="scan already in progress")
    try:
        jobs = await asyncio.to_thread(
            app.state.container.scan_documents.execute,
            bucket=request.bucket,
            prefix=request.prefix,
        )
    finally:
        _scan_lock.release()

    if not jobs:
        return {"status": "scan started", "queued": 0}

    queued = app.state.dispatcher.enqueue_jobs(jobs, app.state.container)
    return {"status": "scan started", "queued": queued}


@app.get("/status/{doc_id}")
async def get_status(doc_id: str):
    result = await asyncio.to_thread(
        app.state.container.get_document_status.execute, doc_id
    )
    if result is None:
        raise HTTPException(status_code=404, detail=f"doc_id={doc_id} not found")
    return {
        "doc_id": result.doc_id,
        "status": result.status,
        "file_path": result.file_path,
        "source_s3_uri": result.source_s3_uri,
        "markdown_s3_uri": result.markdown_s3_uri,
        "file_type": result.file_type,
        "section_count": result.section_count,
        "parser_version": result.parser_version,
        "caption_model": result.caption_model,
        "embedding_model": result.embedding_model,
        "uploaded_at": result.uploaded_at,
        "processed_at": result.processed_at,
    }


@app.get("/health")
async def health():
    container = app.state.container
    degraded_reasons = list(container.degraded_reasons)
    status = "degraded" if degraded_reasons else "ok"
    dispatcher_stats = app.state.dispatcher.snapshot()
    payload = {
        "status": status,
        **container.system_info,
        "scanner": "enabled" if (settings.USE_S3 and settings.SCAN_INTERVAL_SECONDS > 0) else "disabled",
        "dispatcher": dispatcher_stats,
        "degraded_reasons": degraded_reasons,
    }
    return JSONResponse(status_code=200 if status == "ok" else 503, content=payload)
