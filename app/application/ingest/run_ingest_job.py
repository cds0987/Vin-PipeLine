from __future__ import annotations

import logging
import time

from app.application.ingest.index_sections import DocumentIndexService
from app.domain.documents.models import IngestJob
from app.domain.documents.statuses import DocumentStatus
from app.ports.ai import SectionEmbedder
from app.ports.parsing import DocumentParser
from app.ports.repositories import DocumentRepository, IngestClaimRepository, JobLogRepository
from app.ports.sectioning import SectionCaptioner, SectionSplitter
from app.ports.storage import BinaryReader, MarkdownStore

log = logging.getLogger(__name__)


class RunIngestJob:
    def __init__(
        self,
        binary_reader: BinaryReader,
        parser: DocumentParser,
        markdown_store: MarkdownStore,
        section_splitter: SectionSplitter,
        section_captioner: SectionCaptioner,
        section_embedder: SectionEmbedder,
        index_service: DocumentIndexService,
        document_repository: DocumentRepository,
        ingest_claim_repository: IngestClaimRepository,
        job_log_repository: JobLogRepository,
    ) -> None:
        self._binary_reader = binary_reader
        self._parser = parser
        self._markdown_store = markdown_store
        self._section_splitter = section_splitter
        self._section_captioner = section_captioner
        self._section_embedder = section_embedder
        self._index_service = index_service
        self._document_repository = document_repository
        self._ingest_claim_repository = ingest_claim_repository
        self._job_log_repository = job_log_repository

    def execute(self, job: IngestJob, deadline_monotonic: float | None = None) -> dict:
        def _check_deadline(stage: str) -> None:
            if deadline_monotonic is not None and time.perf_counter() > deadline_monotonic:
                raise TimeoutError(f"doc_id={job.doc_id}: ingest timeout exceeded at stage={stage}")

        started_at = time.perf_counter()
        try:
            if not self._ingest_claim_repository.try_claim_ingest(job):
                return {"doc_id": job.doc_id, "status": "skipped", "section_count": 0}

            log.info(
                "ingest_started doc_id=%s source_s3_uri=%s file_type=%s document_type=%s",
                job.doc_id, job.file_uri,
                job.file_uri.rsplit(".", 1)[-1].lower() if "." in job.file_uri else None,
                job.document_type,
            )

            _check_deadline("read")
            file_bytes = self._binary_reader.read(job.file_uri)

            _check_deadline("parse")
            t0 = time.perf_counter()
            markdown_doc = self._parser.parse(job, file_bytes)
            markdown_doc = markdown_doc.model_copy(update={"markdown_content": self._normalize(markdown_doc.markdown_content)})
            job = job.model_copy(update={"language": self._detect_language(markdown_doc.markdown_content)})
            if not markdown_doc.markdown_content.strip():
                raise ValueError(f"doc_id={job.doc_id}: parse produced empty markdown")
            log.info(
                "parse_completed doc_id=%s parser_version=%s markdown_length=%d duration_ms=%d",
                job.doc_id, markdown_doc.parser_version,
                len(markdown_doc.markdown_content),
                round((time.perf_counter() - t0) * 1000),
            )

            _check_deadline("markdown_store")
            t0 = time.perf_counter()
            markdown_doc = self._markdown_store.save(markdown_doc)
            log.info(
                "markdown_saved doc_id=%s markdown_s3_uri=%s duration_ms=%d",
                job.doc_id, markdown_doc.markdown_s3_uri,
                round((time.perf_counter() - t0) * 1000),
            )

            _check_deadline("split")
            t0 = time.perf_counter()
            sections = self._section_splitter.split(markdown_doc, job)
            if not sections:
                raise ValueError(f"doc_id={job.doc_id}: markdown produced no sections")
            log.info(
                "sections_split doc_id=%s section_count=%d duration_ms=%d",
                job.doc_id, len(sections),
                round((time.perf_counter() - t0) * 1000),
            )

            _check_deadline("caption")
            t0 = time.perf_counter()
            sections = self._section_captioner.caption_sections(sections)
            caption_model = sections[0].metadata.get("caption_model", "") if sections else ""
            log.info(
                "captions_generated doc_id=%s section_count=%d caption_model=%s duration_ms=%d",
                job.doc_id, len(sections), caption_model,
                round((time.perf_counter() - t0) * 1000),
            )

            _check_deadline("embed")
            t0 = time.perf_counter()
            sections = self._section_embedder.embed_sections(sections)
            embedding_model = sections[0].metadata.get("embedding_model", "") if sections else ""
            embedding_dim = len(sections[0].embedding) if sections else 0
            log.info(
                "embeddings_generated doc_id=%s section_count=%d embedding_model=%s dim=%d duration_ms=%d",
                job.doc_id, len(sections), embedding_model, embedding_dim,
                round((time.perf_counter() - t0) * 1000),
            )

            _check_deadline("index")
            duration = round(time.perf_counter() - started_at, 3)
            result = self._index_service.index_sections(sections, job, duration_seconds=duration)
            log.info(
                "ingest_completed doc_id=%s section_count=%d source_s3_uri=%s markdown_s3_uri=%s duration_ms=%d",
                job.doc_id, result.get("section_count", 0),
                result.get("source_s3_uri"), result.get("markdown_s3_uri"),
                round(duration * 1000),
            )
            return result

        except Exception as exc:
            duration = round(time.perf_counter() - started_at, 3)
            self._job_log_repository.record_job(
                doc_id=job.doc_id,
                status="failed",
                duration_seconds=duration,
                error_message=str(exc),
            )
            self._document_repository.update_status(job.doc_id, DocumentStatus.FAILED)
            log.exception(
                "ingest_failed doc_id=%s error_type=%s error=%s duration_ms=%d",
                job.doc_id, type(exc).__name__, exc,
                round(duration * 1000),
            )
            raise

    def _detect_language(self, text: str) -> str:
        if len(text) < 50:
            return "vi"
        try:
            from langdetect import detect
            return detect(text)
        except Exception:
            return "vi"

    def _normalize(self, text: str) -> str:
        import re
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", normalized)
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()
