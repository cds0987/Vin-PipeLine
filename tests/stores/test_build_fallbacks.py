"""
Tests for build_vector_store() and build_metadata_store() fallback behaviour.

When the primary store (Qdrant / Postgres) is unavailable, the builders must:
  - return a degraded in-memory / file fallback
  - return a warning string describing the failure
  - not raise
"""
from __future__ import annotations

import pytest

from utils.stores import (
    FileMetadataStore,
    InMemoryMetadataStore,
    InMemoryVectorStore,
    build_metadata_store,
    build_vector_store,
)


# ── build_vector_store ────────────────────────────────────────────────────────

def test_build_vector_store_memory_returns_no_warning(monkeypatch):
    monkeypatch.setattr("config.settings.VECTOR_STORE", "memory")
    store, warning = build_vector_store()
    assert isinstance(store, InMemoryVectorStore)
    assert warning is None


def test_build_vector_store_qdrant_unavailable_returns_warning(monkeypatch):
    monkeypatch.setattr("config.settings.VECTOR_STORE", "qdrant")

    # Force QdrantStore.__init__ to raise
    monkeypatch.setattr(
        "utils.stores.QdrantStore.__init__",
        lambda self: (_ for _ in ()).throw(ConnectionRefusedError("qdrant down")),
    )

    store, warning = build_vector_store()
    assert isinstance(store, InMemoryVectorStore)
    assert warning is not None
    assert "QdrantStore unavailable" in warning


def test_build_vector_store_warning_contains_reason(monkeypatch):
    monkeypatch.setattr("config.settings.VECTOR_STORE", "qdrant")
    monkeypatch.setattr(
        "utils.stores.QdrantStore.__init__",
        lambda self: (_ for _ in ()).throw(RuntimeError("cannot connect")),
    )
    _, warning = build_vector_store()
    assert "cannot connect" in warning


# ── build_metadata_store ──────────────────────────────────────────────────────

def test_build_metadata_store_memory_returns_no_warning(monkeypatch):
    monkeypatch.setattr("config.settings.METADATA_STORE", "memory")
    store, warning = build_metadata_store()
    assert isinstance(store, InMemoryMetadataStore)
    assert warning is None


def test_build_metadata_store_file_returns_no_warning(monkeypatch, tmp_path):
    monkeypatch.setattr("config.settings.METADATA_STORE", "file")
    store, warning = build_metadata_store()
    assert isinstance(store, FileMetadataStore)
    assert warning is None


def test_build_metadata_store_postgres_unavailable_falls_back(monkeypatch):
    monkeypatch.setattr("config.settings.METADATA_STORE", "postgres")
    monkeypatch.setattr(
        "utils.stores.SQLMetadataStore.__init__",
        lambda self, db_url=None: (_ for _ in ()).throw(Exception("postgres down")),
    )

    store, warning = build_metadata_store()
    assert isinstance(store, FileMetadataStore)
    assert warning is not None
    assert "SQLMetadataStore unavailable" in warning


def test_build_metadata_store_warning_contains_reason(monkeypatch):
    monkeypatch.setattr("config.settings.METADATA_STORE", "postgres")
    monkeypatch.setattr(
        "utils.stores.SQLMetadataStore.__init__",
        lambda self, db_url=None: (_ for _ in ()).throw(Exception("auth failed")),
    )
    _, warning = build_metadata_store()
    assert "auth failed" in warning


# ── fallback store is functional ─────────────────────────────────────────────

def test_fallback_vector_store_is_usable(monkeypatch):
    """The fallback InMemoryVectorStore must accept upsert and search."""
    monkeypatch.setattr("config.settings.VECTOR_STORE", "qdrant")
    monkeypatch.setattr(
        "utils.stores.QdrantStore.__init__",
        lambda self: (_ for _ in ()).throw(Exception("down")),
    )
    from models.ingest_job import ChunkResult
    store, _ = build_vector_store()
    section = ChunkResult(section_id="d1_section_0000", doc_id="d1", section_content="test", embedding=[0.1, 0.2])
    store.upsert([section])
    results = store.search([0.1, 0.2], top_k=5)
    assert results


def test_fallback_metadata_store_is_usable(monkeypatch):
    """The fallback FileMetadataStore must accept upsert and get."""
    monkeypatch.setattr("config.settings.METADATA_STORE", "postgres")
    monkeypatch.setattr(
        "utils.stores.SQLMetadataStore.__init__",
        lambda self, db_url=None: (_ for _ in ()).throw(Exception("down")),
    )
    from models.ingest_job import DocumentRecord
    from datetime import datetime, timezone
    store, _ = build_metadata_store()
    now = datetime.now(timezone.utc)
    doc = DocumentRecord(id="d1", file_path="s3://b/f.pdf", status="pending",
                         uploaded_at=now, updated_at=now)
    store.upsert(doc)
    assert store.get_document("d1") is not None
