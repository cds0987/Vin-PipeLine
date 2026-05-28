from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field

from config import settings
from models.events import DocumentUploaded
from models.ingest_job import PermissionModel
from retrieval.service import RetrievalRequest, RetrievalService
from utils.ai_provider import build_ai_provider
from utils.notifier import notify
from utils.stores import build_metadata_store, build_vector_store


class IngestRequest(BaseModel):
    doc_id: str
    file_uri: str
    uploaded_by: str | None = None
    org_id: str | None = None
    permission: PermissionModel | None = None
    metadata: dict = Field(default_factory=dict)


class RetrieveContextRequest(BaseModel):
    query: str
    user_id: str
    user_roles: list[str] = Field(default_factory=list)
    org_id: str | None = None
    top_k: int = 5


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ai_provider = build_ai_provider()
    app.state.vector_store = build_vector_store()
    app.state.metadata_store = build_metadata_store()
    app.state.retrieval_service = RetrievalService(
        ai_provider=app.state.ai_provider,
        vector_store=app.state.vector_store,
        metadata_store=app.state.metadata_store,
    )
    yield


app = FastAPI(title="DE Ingestion Service", lifespan=lifespan)


@app.post("/ingest")
def ingest(request: IngestRequest):
    event = DocumentUploaded(
        doc_id=request.doc_id,
        s3_uri=request.file_uri,
        uploaded_by=request.uploaded_by or "api",
        org_id=request.org_id,
        metadata=request.metadata,
        permission=request.permission,
    )
    notify(settings.TOPIC_INGEST, event.model_dump(mode="json"))
    return {"doc_id": request.doc_id, "status": "queued"}


@app.post("/retrieve-context")
def retrieve_context(request: RetrieveContextRequest):
    contexts = app.state.retrieval_service.retrieve(
        RetrievalRequest(
            query=request.query,
            user_id=request.user_id,
            user_roles=request.user_roles,
            org_id=request.org_id,
            top_k=request.top_k,
        )
    )
    return {"request_id": str(uuid4()), "contexts": contexts}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "vector_store": settings.VECTOR_STORE,
        "ai_provider": app.state.ai_provider.__class__.__name__,
    }
