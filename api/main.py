from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel, Field

from config import settings
from pipeline.run import run as run_pipeline
from retrieval.service import RetrievalService
from utils.ai_provider import build_ai_provider
from utils.stores import MetadataStore, VectorStore, build_metadata_store, build_vector_store

log = logging.getLogger(__name__)


# ─── Request / Response models ────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=50)


class ScanRequest(BaseModel):
    bucket: str | None = None
    prefix: str | None = None


# ─── Background S3 scanner loop ───────────────────────────────────────────────

def _scanner_loop(ai_provider, vector_store: VectorStore, metadata_store: MetadataStore) -> None:
    """Chạy ngầm — poll S3 mỗi SCAN_INTERVAL_SECONDS giây."""
    from adapters.s3_adapter import S3Scanner

    interval = settings.SCAN_INTERVAL_SECONDS
    log.info("S3 scanner started — interval=%ds bucket=%s prefix=%r",
             interval, settings.S3_BUCKET, settings.SCAN_PREFIX)

    while True:
        try:
            jobs = S3Scanner(metadata_store).scan()
            for job in jobs:
                try:
                    run_pipeline(job, ai_provider=ai_provider,
                                 vector_store=vector_store, metadata_store=metadata_store)
                except Exception as exc:
                    log.error("Pipeline failed doc_id=%s: %s", job.doc_id, exc)
        except Exception as exc:
            log.error("Scanner loop error: %s", exc)
        time.sleep(interval)


# ─── App lifecycle ─────────────────────────────────────────────────────────────

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
        t = threading.Thread(
            target=_scanner_loop,
            args=(app.state.ai_provider, app.state.vector_store, app.state.metadata_store),
            daemon=True,
        )
        t.start()
        log.info("Background S3 scanner thread started")

    yield


app = FastAPI(title="DE Vector Search Engine", lifespan=lifespan)


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/search")
def search(request: SearchRequest):
    """
    Vector search — nhận query text, trả chunks liên quan kèm s3_uri.
    DE không biết user là ai, không filter permission.
    BE tự quyết định dùng kết quả như thế nào.
    """
    results = app.state.retrieval_service.search(request.query, top_k=request.top_k)
    return {"request_id": str(uuid4()), "results": results}


@app.post("/scan")
def trigger_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    """
    Trigger S3 scan thủ công (ops / debug).
    Trả ngay, ingest chạy nền.
    """
    from adapters.s3_adapter import S3Scanner

    def _run():
        jobs = S3Scanner(app.state.metadata_store).scan(
            bucket=request.bucket, prefix=request.prefix
        )
        for job in jobs:
            try:
                run_pipeline(job, ai_provider=app.state.ai_provider,
                             vector_store=app.state.vector_store,
                             metadata_store=app.state.metadata_store)
            except Exception as exc:
                log.error("Pipeline failed doc_id=%s: %s", job.doc_id, exc)

    background_tasks.add_task(_run)
    return {"status": "scan started"}


@app.get("/status/{doc_id}")
def get_status(doc_id: str):
    """Kiểm tra trạng thái ingestion của một document."""
    doc = app.state.metadata_store.get_document(doc_id)
    if doc is None:
        from fastapi import HTTPException
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
