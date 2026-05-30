from __future__ import annotations

from app.domain.documents.models import DocumentRecord, IngestJob, MarkdownDocument, SectionRecord

# Legacy compatibility exports. New code should import from app.domain.*
ChunkResult = SectionRecord

__all__ = [
    "ChunkResult",
    "DocumentRecord",
    "IngestJob",
    "MarkdownDocument",
    "SectionRecord",
]
