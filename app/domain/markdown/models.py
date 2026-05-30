from __future__ import annotations

from pydantic import BaseModel, Field


class MarkdownDocument(BaseModel):
    doc_id: str
    source_uri: str
    markdown_content: str
    markdown_s3_uri: str | None = None
    parser_version: str = "pipeline.parsers.v1"
    title: str | None = None
    metadata: dict = Field(default_factory=dict)
