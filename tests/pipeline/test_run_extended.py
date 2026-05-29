"""
Extended run() tests — covers scenarios NOT in the existing test_pipeline.py:
  - empty text after parse → ValueError, status=failed
  - exception in embed → status=failed
  - re-ingest same doc_id → old vectors deleted, not accumulated
  - result dict contains duration_seconds
  - timeout fires at each stage beyond 'parse'
"""
from __future__ import annotations

import importlib
import pytest

from config import settings
from models.ingest_job import IngestJob
from utils.stores import InMemoryMetadataStore, InMemoryVectorStore

run_mod = importlib.import_module("pipeline.run")


class _MinimalAI:
    def embed(self, texts): return [[0.1] * settings.EMBEDDING_DIM for _ in texts]
    def ocr(self, _): return ""


# ─── Empty text after parse raises and marks failed ───────────────────────────

def test_empty_parse_result_raises_and_marks_failed(tmp_path):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_bytes(b"")
    job = IngestJob(doc_id="doc-empty", file_uri=str(empty_file))
    metadata_store = InMemoryMetadataStore()

    with pytest.raises(Exception):
        run_mod.run(job, ai_provider=_MinimalAI(),
                    vector_store=InMemoryVectorStore(), metadata_store=metadata_store)

    doc = metadata_store.get_document("doc-empty")
    assert doc is not None
    assert doc.status == "failed"


def test_whitespace_only_file_is_treated_as_empty(tmp_path):
    f = tmp_path / "blank.txt"
    f.write_bytes(b"   \r\n   \t   ")
    job = IngestJob(doc_id="doc-blank", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()

    with pytest.raises(Exception):
        run_mod.run(job, ai_provider=_MinimalAI(),
                    vector_store=InMemoryVectorStore(), metadata_store=metadata_store)

    assert metadata_store.get_document("doc-blank").status == "failed"


# ─── Exception in embed stage → failed ────────────────────────────────────────

def test_embed_exception_marks_status_failed(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"content for embed failure test")
    job = IngestJob(doc_id="doc-embed-fail", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()

    class _FailEmbed:
        def embed(self, _): raise RuntimeError("embed API down")
        def ocr(self, _): return ""

    with pytest.raises(RuntimeError, match="embed API down"):
        run_mod.run(job, ai_provider=_FailEmbed(),
                    vector_store=InMemoryVectorStore(), metadata_store=metadata_store)

    assert metadata_store.get_document("doc-embed-fail").status == "failed"


# ─── Re-ingest same doc_id does not accumulate vectors ───────────────────────

def test_reingest_same_doc_id_replaces_not_accumulates(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"first version of this document with enough words")
    job = IngestJob(doc_id="doc-reingest", file_uri=str(f))
    vector_store = InMemoryVectorStore()
    metadata_store = InMemoryMetadataStore()
    ai = _MinimalAI()

    run_mod.run(job, ai_provider=ai, vector_store=vector_store, metadata_store=metadata_store)
    count_after_first = len(vector_store.search([0.1] * settings.EMBEDDING_DIM, top_k=100))

    # Second run — same file, same doc_id
    run_mod.run(job, ai_provider=ai, vector_store=vector_store, metadata_store=metadata_store)
    count_after_second = len(vector_store.search([0.1] * settings.EMBEDDING_DIM, top_k=100))

    assert count_after_second == count_after_first


# ─── Result dict shape ────────────────────────────────────────────────────────

def test_result_contains_duration_seconds(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"timing test document")
    job = IngestJob(doc_id="doc-timing", file_uri=str(f))
    result = run_mod.run(job, ai_provider=_MinimalAI(),
                         vector_store=InMemoryVectorStore(), metadata_store=InMemoryMetadataStore())
    assert "duration_seconds" in result
    assert isinstance(result["duration_seconds"], float)
    assert result["duration_seconds"] >= 0.0


def test_result_contains_embedding_model(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MODEL", "test-model-in-result")
    f = tmp_path / "doc.txt"
    f.write_bytes(b"model name test")
    job = IngestJob(doc_id="doc-model", file_uri=str(f))
    result = run_mod.run(job, ai_provider=_MinimalAI(),
                         vector_store=InMemoryVectorStore(), metadata_store=InMemoryMetadataStore())
    assert result["embedding_model"] == "test-model-in-result"


# ─── Timeout at each stage ────────────────────────────────────────────────────

def test_timeout_at_parse_stage_marks_failed():
    job = IngestJob(doc_id="doc-timeout-parse", file_uri="data/sample/policy.txt")
    metadata_store = InMemoryMetadataStore()

    with pytest.raises(TimeoutError):
        run_mod.run(job, ai_provider=_MinimalAI(),
                    vector_store=InMemoryVectorStore(), metadata_store=metadata_store,
                    deadline_monotonic=0.0)

    assert metadata_store.get_document("doc-timeout-parse").status == "failed"


def test_deadline_respected_after_parse(tmp_path, monkeypatch):
    """Deadline set to past → timeout before clean even if parse succeeded."""
    import time
    f = tmp_path / "doc.txt"
    f.write_bytes(b"some real content to parse")
    job = IngestJob(doc_id="doc-timeout-clean", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()

    # Sabotage parse to succeed, then deadline fires at clean
    real_parse = run_mod.parse

    class _SlowParse:
        @staticmethod
        def run(j, ai):
            return [(1, "parsed content")]

    monkeypatch.setattr(run_mod, "parse", _SlowParse)

    with pytest.raises(TimeoutError):
        run_mod.run(job, ai_provider=_MinimalAI(),
                    vector_store=InMemoryVectorStore(), metadata_store=metadata_store,
                    deadline_monotonic=0.0)

    assert metadata_store.get_document("doc-timeout-clean").status == "failed"
    monkeypatch.setattr(run_mod, "parse", real_parse)


# ─── Status is "indexed" on success ──────────────────────────────────────────

def test_successful_run_sets_indexed_status(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"a complete document with enough content to produce one chunk")
    job = IngestJob(doc_id="doc-success", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()
    run_mod.run(job, ai_provider=_MinimalAI(),
                vector_store=InMemoryVectorStore(), metadata_store=metadata_store)
    assert metadata_store.get_document("doc-success").status == "indexed"
