from __future__ import annotations

from pydantic import BaseModel, Field


class SectionRecord(BaseModel):
    section_id: str
    doc_id: str
    section_content: str
    caption: str = ""
    embedding: list[float] = Field(default_factory=list)
    heading: str = ""
    heading_path: list[str] = Field(default_factory=list)
    section_order: int = 0
    markdown_s3_uri: str | None = None
    source_s3_uri: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    # Access control — optional, for document-level ACL enforcement
    owner_scope: str | None = None
    department_scope: str | None = None
    access_tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    @property
    def title(self) -> str:
        if self.heading_path:
            return " > ".join(self.heading_path)
        return "Untitled"
