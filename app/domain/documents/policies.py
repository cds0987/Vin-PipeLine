"""
app.domain.documents.policies
──────────────────────────────
Business rules that govern document lifecycle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.documents.models import DocumentRecord
from app.domain.documents.statuses import DocumentStatus


def is_stale_indexing(doc: DocumentRecord, stale_seconds: int) -> bool:
    """Return True if a document stuck in INDEXING status has been there long enough to reclaim."""
    if doc.status != DocumentStatus.INDEXING:
        return False
    if stale_seconds == 0:
        return True
    updated_at = doc.updated_at or doc.uploaded_at
    # SQLite returns timezone-naive datetimes; treat them as UTC.
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - updated_at >= timedelta(seconds=stale_seconds)
