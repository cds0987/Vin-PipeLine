from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class PermissionModel(BaseModel):
    visibility: str = "private"
    allowed_roles: list[str] = Field(default_factory=list)
    allowed_users: list[str] = Field(default_factory=list)
    owner_id: str | None = None
    org_id: str | None = None


class IngestJob(BaseModel):
    doc_id: str
    file_uri: str
    language: str = "vi"
    document_type: str = "general"
    permission: PermissionModel | None = None
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
    file_type: str | None = None        # pdf | docx | txt | html | image — format kỹ thuật
    document_type: str = "general"      # policy | contract | manual — phân loại nghiệp vụ
    language: str = "vi"
    status: str = "pending"
    uploaded_by: str | None = None
    org_id: str | None = None
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
