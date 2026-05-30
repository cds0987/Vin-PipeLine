from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.bootstrap.container import Container, build_container
from config import settings
from models.ingest_job import IngestJob

log = logging.getLogger(__name__)

_scan_lock = threading.Lock()


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


def _run_single_job(job: IngestJob, container: Container) -> dict:
    deadline_monotonic = None
    if settings.SCAN_JOB_TIMEOUT_SECONDS > 0:
        deadline_monotonic = time.perf_counter() + settings.SCAN_JOB_TIMEOUT_SECONDS
    return container.run_ingest_job.execute(job, deadline_monotonic=deadline_monotonic)


def _run_jobs(jobs: list[IngestJob], container: Container) -> int:
    ran = 0
    if not jobs:
        return ran
    with ThreadPoolExecutor(max_workers=settings.SCAN_MAX_WORKERS) as pool:
        futures = {pool.submit(_run_single_job, job, container): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                result = future.result()
                if result.get("status") != "skipped":
                    ran += 1
            except Exception as exc:
                log.error("Pipeline failed doc_id=%s: %s", job.doc_id, exc)
    return ran


def _scan_and_run_once(container: Container) -> int:
    if not _scan_lock.acquire(blocking=False):
        log.warning("Scan already in progress - skipping scanner cycle")
        return 0
    try:
        jobs = container.scan_documents.execute()
    finally:
        _scan_lock.release()
    return _run_jobs(jobs, container)


def _scanner_loop(container: Container) -> None:
    interval = settings.SCAN_INTERVAL_SECONDS
    log.info(
        "S3 scanner started - interval=%ds bucket=%s prefix=%r",
        interval,
        settings.S3_BUCKET,
        settings.SCAN_PREFIX,
    )
    while True:
        try:
            _scan_and_run_once(container)
        except Exception as exc:
            log.error("Scanner loop error: %s", exc)
        time.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = build_container()
    app.state.container = container

    if settings.USE_S3 and settings.SCAN_INTERVAL_SECONDS > 0:
        thread = threading.Thread(target=_scanner_loop, args=(container,), daemon=True)
        thread.start()
        log.info("Background S3 scanner thread started")

    yield


app = FastAPI(title="DE Vector Search Engine", lifespan=lifespan)


@app.post("/search")
def search(request: SearchRequest):
    request_id = str(uuid4())
    results = app.state.container.search_sections.search(
        request.query, top_k=request.top_k, request_id=request_id
    )
    return {
        "request_id": request_id,
        "results": [result.model_dump() for result in results],
    }


@app.post("/scan")
def trigger_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    if not _scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="scan already in progress")
    try:
        jobs = app.state.container.scan_documents.execute(bucket=request.bucket, prefix=request.prefix)
    finally:
        _scan_lock.release()

    if not jobs:
        return {"status": "scan started", "queued": 0}

    background_tasks.add_task(_run_jobs, jobs, app.state.container)
    return {"status": "scan started", "queued": len(jobs)}


@app.get("/status/{doc_id}")
def get_status(doc_id: str):
    result = app.state.container.get_document_status.execute(doc_id)
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
def health():
    container = app.state.container
    degraded_reasons = list(container.degraded_reasons)
    status = "degraded" if degraded_reasons else "ok"
    payload = {
        "status": status,
        **container.system_info,
        "scanner": "enabled" if (settings.USE_S3 and settings.SCAN_INTERVAL_SECONDS > 0) else "disabled",
        "degraded_reasons": degraded_reasons,
    }
    return JSONResponse(status_code=200 if status == "ok" else 503, content=payload)
