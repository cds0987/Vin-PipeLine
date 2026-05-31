from __future__ import annotations

from dataclasses import dataclass

from app.application.ingest.index_sections import DocumentIndexService
from app.application.ingest.run_ingest_job import RunIngestJob
from app.application.scan.scan_documents import ScanDocuments
from app.application.search.search_sections import SearchSections
from app.application.status.get_document_status import GetDocumentStatus
from app.infrastructure.ai.captioner import AISectionCaptioner
from app.infrastructure.ai.embedder import AISectionEmbedder
from app.infrastructure.parser.router import RouterDocumentParser
from app.infrastructure.repositories.document_repository import MetadataStoreRepository
from app.infrastructure.scanning.s3_source_scanner import S3SourceScanner
from app.infrastructure.sectioning.heading_splitter import HeadingSectionSplitter
from app.infrastructure.storage.binary_reader import StorageBinaryReader
from app.infrastructure.storage.markdown_store import ArtifactMarkdownStore
from app.infrastructure.vector.section_index import VectorStoreSectionIndex
from config import settings
from utils.ai_provider import AIProvider, MockAIProvider, build_ai_provider
from utils.batch_embedder import BatchEmbedder
from utils.stores import MetadataStore, VectorStore, build_metadata_store, build_vector_store


@dataclass
class Container:
    degraded_reasons: list[str]
    system_info: dict
    run_ingest_job: RunIngestJob
    search_sections: SearchSections
    scan_documents: ScanDocuments
    get_document_status: GetDocumentStatus
    batch_embedder: BatchEmbedder


def build_container(
    ai_provider: AIProvider | None = None,
    vector_store: VectorStore | None = None,
    metadata_store: MetadataStore | None = None,
) -> Container:
    resolved_ai, ai_warning = (ai_provider, None) if ai_provider else build_ai_provider()
    resolved_vector, vector_warning = (vector_store, None) if vector_store else build_vector_store()
    resolved_metadata, metadata_warning = (metadata_store, None) if metadata_store else build_metadata_store()

    batch_embedder = BatchEmbedder(
        provider=resolved_ai,
        max_batch_size=settings.EMBED_MAX_BATCH_SIZE,
        window_ms=settings.EMBED_BATCH_WINDOW_MS,
        cache_size=settings.EMBED_CACHE_SIZE,
    )

    parser = RouterDocumentParser(resolved_ai)
    markdown_store = ArtifactMarkdownStore()
    splitter = HeadingSectionSplitter()
    captioner = AISectionCaptioner(resolved_ai)
    embedder = AISectionEmbedder(batch_embedder)
    section_index = VectorStoreSectionIndex(resolved_vector)
    repository = MetadataStoreRepository(resolved_metadata)
    index_service = DocumentIndexService(section_index, repository, repository)
    ingest = RunIngestJob(
        binary_reader=StorageBinaryReader(),
        parser=parser,
        markdown_store=markdown_store,
        section_splitter=splitter,
        section_captioner=captioner,
        section_embedder=embedder,
        index_service=index_service,
        document_repository=repository,
        ingest_claim_repository=repository,
        job_log_repository=repository,
    )
    search = SearchSections(resolved_ai, section_index)
    scan = ScanDocuments(S3SourceScanner(resolved_metadata))
    status = GetDocumentStatus(repository)

    degraded_reasons = [r for r in (ai_warning, vector_warning, metadata_warning) if r]
    if ai_provider is None and isinstance(resolved_ai, MockAIProvider) and not settings.AI_API_KEY:
        degraded_reasons.append("AI provider is running in mock fallback mode.")

    system_info = {
        "vector_store": type(resolved_vector).__name__,
        "metadata_store": type(resolved_metadata).__name__,
        "ai_provider": type(resolved_ai).__name__,
    }

    return Container(
        degraded_reasons=degraded_reasons,
        system_info=system_info,
        run_ingest_job=ingest,
        search_sections=search,
        scan_documents=scan,
        get_document_status=status,
        batch_embedder=batch_embedder,
    )
