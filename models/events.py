from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from models.ingest_job import PermissionModel


class EventMetadata(BaseModel):
    file_name: str | None = None
    document_type: str = "general"
    language: str = "vi"
    file_size_bytes: int | None = None


class DocumentUploaded(BaseModel):
    event: str = "DocumentUploaded"
    schema_version: str = "1.0"
    doc_id: str
    s3_uri: str
    uploaded_by: str
    org_id: str | None = None
    metadata: EventMetadata = Field(default_factory=EventMetadata)
    permission: PermissionModel | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EmbeddingDone(BaseModel):
    event: str = "EmbeddingDone"
    schema_version: str = "1.0"
    doc_id: str
    chunk_count: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IndexingFailed(BaseModel):
    event: str = "IndexingFailed"
    schema_version: str = "1.0"
    doc_id: str
    reason: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
