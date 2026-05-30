from __future__ import annotations

from pydantic import BaseModel, Field


class SectionSearchResult(BaseModel):
    section_id: str
    document_id: str
    document_name: str
    caption: str
    section_content: str
    markdown_s3_uri: str | None = None
    source_s3_uri: str | None = None
    score: float
    heading_path: list[str] = Field(default_factory=list)
