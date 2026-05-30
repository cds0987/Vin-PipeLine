from __future__ import annotations

from pathlib import Path

from app.domain.documents.models import IngestJob, MarkdownDocument
from app.ports.parsing import DocumentParser
from config import settings
from pipeline import parsers
from utils.ai_provider import AIProvider


class RouterDocumentParser(DocumentParser):
    def __init__(self, ai_provider: AIProvider) -> None:
        self._ai_provider = ai_provider

    def parse(self, job: IngestJob, file_bytes: bytes) -> MarkdownDocument:
        suffix = Path(job.file_uri).suffix.lower()
        markdown = parsers.run(file_bytes, suffix, ai_provider=self._ai_provider)
        return MarkdownDocument(
            doc_id=job.doc_id,
            source_uri=job.file_uri,
            markdown_content=markdown,
            parser_version=settings.PARSER_VERSION,
            title=job.file_name,
            metadata={
                "file_type": suffix.lstrip(".") or None,
                "document_type": job.document_type,
            },
        )
