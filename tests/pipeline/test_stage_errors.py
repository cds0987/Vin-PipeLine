"""
Tests for stage error handling in the clean architecture ingest use case.

Each failing stage must:
  - propagate the exception to the caller
  - record a failed job in the metadata store
  - set the document status to "failed"
"""
from __future__ import annotations

import pytest

from app.application.ingest.index_sections import DocumentIndexService
from app.application.ingest.run_ingest_job import RunIngestJob
from app.domain.documents.models import IngestJob, MarkdownDocument, SectionRecord
from app.infrastructure.repositories.document_repository import MetadataStoreRepository
from app.infrastructure.storage.binary_reader import StorageBinaryReader
from app.infrastructure.storage.markdown_store import ArtifactMarkdownStore
from app.infrastructure.vector.section_index import VectorStoreSectionIndex
from config import settings
from utils.stores import InMemoryMetadataStore, InMemoryVectorStore


class _MinimalParser:
    def __init__(self, markdown: str = "content") -> None:
        self._markdown = markdown

    def parse(self, job, file_bytes):
        return MarkdownDocument(
            doc_id=job.doc_id,
            source_uri=job.file_uri,
            markdown_content=self._markdown,
        )


class _MinimalSplitter:
    def split(self, document, job):
        return [
            SectionRecord(
                section_id=f"{job.doc_id}_section_0000",
                doc_id=job.doc_id,
                section_content=document.markdown_content,
                source_s3_uri=job.file_uri,
                markdown_s3_uri=document.markdown_s3_uri,
            )
        ]


class _MinimalCaptioner:
    def caption_sections(self, sections):
        for section in sections:
            section.caption = section.section_content[:80]
        return sections


class _MinimalEmbedder:
    def embed_sections(self, sections):
        for section in sections:
            section.embedding = [0.1] * settings.EMBEDDING_DIM
        return sections


def _usecase(
    parser=None,
    splitter=None,
    captioner=None,
    embedder=None,
    index_service=None,
    metadata_store=None,
    vector_store=None,
):
    metadata_store = metadata_store or InMemoryMetadataStore()
    vector_store = vector_store or InMemoryVectorStore()
    repository = MetadataStoreRepository(metadata_store)
    return RunIngestJob(
        binary_reader=StorageBinaryReader(),
        parser=parser or _MinimalParser(),
        markdown_store=ArtifactMarkdownStore(),
        section_splitter=splitter or _MinimalSplitter(),
        section_captioner=captioner or _MinimalCaptioner(),
        section_embedder=embedder or _MinimalEmbedder(),
        index_service=index_service or DocumentIndexService(
            VectorStoreSectionIndex(vector_store),
            repository,
            repository,
        ),
        document_repository=repository,
        ingest_claim_repository=repository,
        job_log_repository=repository,
    ), metadata_store


def test_split_stage_exception_marks_failed(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"content to split")
    job = IngestJob(doc_id="split-fail", file_uri=str(f))

    class _BadSplitter:
        def split(self, document, job): raise ValueError("splitter broken")

    usecase, metadata_store = _usecase(splitter=_BadSplitter())

    with pytest.raises(ValueError, match="splitter broken"):
        usecase.execute(job)

    assert metadata_store.get_document("split-fail").status == "failed"


def test_caption_stage_exception_marks_failed(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"content to caption")
    job = IngestJob(doc_id="caption-fail", file_uri=str(f))

    class _BadCaptioner:
        def caption_sections(self, sections): raise RuntimeError("caption stage exploded")

    usecase, metadata_store = _usecase(captioner=_BadCaptioner())

    with pytest.raises(RuntimeError, match="caption stage exploded"):
        usecase.execute(job)

    doc = metadata_store.get_document("caption-fail")
    assert doc is not None
    assert doc.status == "failed"


def test_index_stage_exception_marks_failed(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"content for index stage failure test")
    job = IngestJob(doc_id="index-fail", file_uri=str(f))

    class _BadIndexService:
        def index_sections(self, *args, **kwargs): raise IOError("qdrant write failed")

    usecase, metadata_store = _usecase(index_service=_BadIndexService())

    with pytest.raises(IOError, match="qdrant write failed"):
        usecase.execute(job)

    assert metadata_store.get_document("index-fail").status == "failed"


def test_failed_job_recorded_with_error_message(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"content")
    job = IngestJob(doc_id="job-record", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()
    recorded_jobs = []
    original_record = metadata_store.record_job

    def _spy_record(doc_id, status, **kwargs):
        recorded_jobs.append({"doc_id": doc_id, "status": status, **kwargs})
        return original_record(doc_id, status, **kwargs)

    metadata_store.record_job = _spy_record

    class _BadSplitter:
        def split(self, document, job): raise RuntimeError("specific error message")

    usecase, _metadata_store = _usecase(splitter=_BadSplitter(), metadata_store=metadata_store)

    with pytest.raises(RuntimeError):
        usecase.execute(job)

    failed = [j for j in recorded_jobs if j["status"] == "failed"]
    assert failed, "No failed job recorded"
    assert "specific error message" in (failed[0].get("error_message") or "")


def test_try_claim_ingest_skip_returns_skipped_status(tmp_path, monkeypatch):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"any content")
    job = IngestJob(doc_id="skip-doc", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()

    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 3600)
    repository = MetadataStoreRepository(metadata_store)
    repository.try_claim_ingest(job)

    usecase, _metadata_store = _usecase(metadata_store=metadata_store)
    result = usecase.execute(job)

    assert result["status"] == "skipped"
    assert result["section_count"] == 0
    assert result["doc_id"] == "skip-doc"


def test_try_claim_ingest_skip_does_not_overwrite_indexing_status(tmp_path, monkeypatch):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"any content")
    job = IngestJob(doc_id="no-overwrite", file_uri=str(f))
    metadata_store = InMemoryMetadataStore()

    monkeypatch.setattr("config.settings.STALE_INDEXING_SECONDS", 3600)
    repository = MetadataStoreRepository(metadata_store)
    repository.try_claim_ingest(job)

    usecase, _metadata_store = _usecase(metadata_store=metadata_store)
    usecase.execute(job)

    doc = metadata_store.get_document("no-overwrite")
    assert doc.status == "indexing"
