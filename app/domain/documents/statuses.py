"""
Document ingest status constants.

Usage:
    from app.domain.documents.statuses import DocumentStatus

    repo.update_status(doc_id, DocumentStatus.INDEXING)
    if doc.status == DocumentStatus.FAILED:
        ...
"""
from __future__ import annotations


class DocumentStatus:
    PENDING = "pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    FAILED = "failed"

    ALL = {PENDING, INDEXING, INDEXED, FAILED}
    TERMINAL = {INDEXED, FAILED}
    RETRIABLE = {PENDING, FAILED}
