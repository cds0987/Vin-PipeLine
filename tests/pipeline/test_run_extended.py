from __future__ import annotations

import asyncio

import pytest

from app.application.ingest.index_sections import DocumentIndexService
from app.application.ingest.run_ingest_job import RunIngestJob
from app.domain.documents.models import IngestJob, MarkdownDocument, SectionRecord
from app.infrastructure.repositories.document_repository import MetadataStoreRepository
from app.infrastructure.storage.binary_reader import StorageBinaryReader
from app.infrastructure.storage.markdown_store import ArtifactMarkdownStore
from app.infrastructure.vector.section_index import VectorStoreSectionIndex
from config import settings
from pipeline.run import run
from utils.stores import InMemoryMetadataStore, InMemoryVectorStore


class _MinimalAI:
    def embed(self, texts): return [[0.1] * settings.EMBEDDING_DIM for _ in texts]
    def caption(self, texts): return [text[:120] for text in texts]
    def ocr(self, _): return ""
    def get_llm_client(self): return None


class _Parser:
    def __init__(self, markdown: str) -> None:
        self._markdown = markdown

    def parse(self, job, file_bytes):
        return MarkdownDocument(
            doc_id=job.doc_id,
            source_uri=job.file_uri,
            markdown_content=self._markdown,
        )


class _Splitter:
    def split(self, document, job):
        if not document.markdown_content.strip():
            return []
        return [
            SectionRecord(
                section_id=f"{job.doc_id}_section_0000",
                doc_id=job.doc_id,
                section_content=document.markdown_content,
                source_s3_uri=job.file_uri,
                markdown_s3_uri=document.markdown_s3_uri,
            )
        ]


class _Captioner:
    async def caption_sections(self, sections):
        for section in sections:
            section.caption = section.section_content[:80]
        return sections


class _Embedder:
    async def embed_sections(self, sections):
        for section in sections:
            section.embedding = [0.1] * settings.EMBEDDING_DIM
        return sections


def _usecase(
    parser,
    splitter=None,
    captioner=None,
    embedder=None,
    vector_store=None,
    metadata_store=None,
):
    vector_store = vector_store or InMemoryVectorStore()
    metadata_store = metadata_store or InMemoryMetadataStore()
    repository = MetadataStoreRepository(metadata_store)
    return RunIngestJob(
        binary_reader=StorageBinaryReader(),
        parser=parser,
        markdown_store=ArtifactMarkdownStore(),
        section_splitter=splitter or _Splitter(),
        section_captioner=captioner or _Captioner(),
        section_embedder=embedder or _Embedder(),
        index_service=DocumentIndexService(
            VectorStoreSectionIndex(vector_store),
            repository,
            repository,
        ),
        document_repository=repository,
        ingest_claim_repository=repository,
        job_log_repository=repository,
    ), vector_store, metadata_store


def test_empty_parse_result_raises_and_marks_failed(tmp_path):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_bytes(b"")
    job = IngestJob(doc_id="doc-empty", file_uri=str(empty_file))
    usecase, _vector_store, metadata_store = _usecase(_Parser(""))

    with pytest.raises(ValueError, match="empty markdown"):
        asyncio.run(usecase.execute(job))

    doc = metadata_store.get_document("doc-empty")
    assert doc is not None
    assert doc.status == "failed"


def test_whitespace_only_markdown_is_treated_as_empty(tmp_path):
    f = tmp_path / "blank.txt"
    f.write_bytes(b"   \r\n   \t   ")
    job = IngestJob(doc_id="doc-blank", file_uri=str(f))
    usecase, _vector_store, metadata_store = _usecase(_Parser("   \n\n "))

    with pytest.raises(ValueError, match="empty markdown"):
        asyncio.run(usecase.execute(job))

    assert metadata_store.get_document("doc-blank").status == "failed"


def test_embed_exception_marks_status_failed(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"content for embed failure test")
    job = IngestJob(doc_id="doc-embed-fail", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()

    class _FailEmbedder:
        async def embed_sections(self, sections): raise RuntimeError("embed API down")

    usecase, _vector_store, metadata_store = _usecase(
        _Parser("content for embed failure test"),
        embedder=_FailEmbedder(),
        metadata_store=metadata_store,
    )

    with pytest.raises(RuntimeError, match="embed API down"):
        asyncio.run(usecase.execute(job))

    assert metadata_store.get_document("doc-embed-fail").status == "failed"


def test_reingest_same_doc_id_replaces_not_accumulates(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"first version of this document with enough words")
    job = IngestJob(doc_id="doc-reingest", file_uri=str(f))
    vector_store = InMemoryVectorStore()
    metadata_store = InMemoryMetadataStore()
    ai = _MinimalAI()

    run(job, ai_provider=ai, vector_store=vector_store, metadata_store=metadata_store)
    count_after_first = len(vector_store.search([0.1] * settings.EMBEDDING_DIM, top_k=100))

    run(job, ai_provider=ai, vector_store=vector_store, metadata_store=metadata_store)
    count_after_second = len(vector_store.search([0.1] * settings.EMBEDDING_DIM, top_k=100))

    assert count_after_second == count_after_first


def test_result_contains_duration_seconds(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"timing test document")
    job = IngestJob(doc_id="doc-timing", file_uri=str(f))
    result = run(
        job,
        ai_provider=_MinimalAI(),
        vector_store=InMemoryVectorStore(),
        metadata_store=InMemoryMetadataStore(),
    )
    assert "duration_seconds" in result
    assert isinstance(result["duration_seconds"], float)
    assert result["duration_seconds"] >= 0.0


def test_result_contains_embedding_model(tmp_path, monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MODEL", "test-model-in-result")
    f = tmp_path / "doc.txt"
    f.write_bytes(b"model name test")
    job = IngestJob(doc_id="doc-model", file_uri=str(f))
    result = run(
        job,
        ai_provider=_MinimalAI(),
        vector_store=InMemoryVectorStore(),
        metadata_store=InMemoryMetadataStore(),
    )
    assert result["embedding_model"] == "test-model-in-result"


def test_timeout_at_parse_stage_marks_failed(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"parse stage timeout")
    job = IngestJob(doc_id="doc-timeout-parse", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()
    usecase, _vector_store, metadata_store = _usecase(_Parser("content"), metadata_store=metadata_store)

    with pytest.raises(TimeoutError):
        asyncio.run(usecase.execute(job, deadline_monotonic=0.0))

    assert metadata_store.get_document("doc-timeout-parse").status == "failed"


def test_deadline_respected_after_parse(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"some real content to parse")
    job = IngestJob(doc_id="doc-timeout-split", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()

    class _SlowSplitter:
        def split(self, document, job):
            raise TimeoutError("forced after parse")

    usecase, _vector_store, metadata_store = _usecase(
        _Parser("parsed content"),
        splitter=_SlowSplitter(),
        metadata_store=metadata_store,
    )

    with pytest.raises(TimeoutError):
        asyncio.run(usecase.execute(job))

    assert metadata_store.get_document("doc-timeout-split").status == "failed"


def test_successful_run_sets_indexed_status(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"a complete document with enough content to produce one section")
    job = IngestJob(doc_id="doc-success", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()
    run(
        job,
        ai_provider=_MinimalAI(),
        vector_store=InMemoryVectorStore(),
        metadata_store=metadata_store,
    )
    assert metadata_store.get_document("doc-success").status == "indexed"
