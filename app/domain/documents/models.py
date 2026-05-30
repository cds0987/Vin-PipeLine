"""
app.domain.documents.models
────────────────────────────
Canonical domain models for source documents and ingest jobs.

MarkdownDocument and SectionRecord live in their own modules
(domain/markdown/models.py and domain/sections/models.py) and are
re-exported here for backward compatibility.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

# ── Re-exports from canonical modules ─────────────────────────────────────────
from app.domain.markdown.models import MarkdownDocument
from app.domain.sections.models import SectionRecord

__all__ = [
    "IngestJob",
    "MarkdownDocument",
    "SectionRecord",
    "DocumentRecord",
]


class IngestJob(BaseModel):
    doc_id: str
    file_uri: str
    language: str = "vi"
    document_type: str = "general"
    s3_last_modified: datetime | None = None
    file_name: str | None = None
    metadata: dict = Field(default_factory=dict)


class DocumentRecord(BaseModel):
    id: str
    file_path: str
    file_name: str | None = None
    file_type: str | None = None
    document_type: str = "general"
    title: str | None = None
    language: str = "vi"
    status: str = "pending"
    total_chunks: int | None = None
    section_count: int | None = None
    markdown_s3_uri: str | None = None
    source_s3_uri: str | None = None
    parser_version: str | None = None
    caption_model: str | None = None
    embedding_model: str | None = None
    s3_last_modified: datetime | None = None
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    processed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Access control — optional, for future document-level ACL enforcement
    owner_scope: str | None = None
    department_scope: str | None = None
    access_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _default_source_uri(self) -> "DocumentRecord":
        if self.section_count is None and self.total_chunks is not None:
            self.section_count = self.total_chunks
        if self.total_chunks is None and self.section_count is not None:
            self.total_chunks = self.section_count
        if self.source_s3_uri is None:
            self.source_s3_uri = self.file_path
        return self
