from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class IngestJob(BaseModel):
    doc_id: str
    file_uri: str
    language: str = "vi"
    document_type: str = "general"
    s3_last_modified: datetime | None = None
    file_name: str | None = None
    metadata: dict = Field(default_factory=dict)


class ChunkResult(BaseModel):
    chunk_id: str
    doc_id: str
    content: str
    embedding: list[float] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    metadata: dict = Field(default_factory=dict)


class DocumentRecord(BaseModel):
    id: str
    file_path: str
    file_name: str | None = None
    file_type: str | None = None        # pdf | docx | txt | html | image
    document_type: str = "general"
    title: str | None = None
    language: str = "vi"
    status: str = "pending"             # pending | indexing | indexed | failed
    total_chunks: int | None = None
    s3_last_modified: datetime | None = None
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
