from __future__ import annotations

from dataclasses import dataclass

from app.ports.repositories import DocumentRepository


@dataclass
class DocumentStatusResult:
    doc_id: str
    status: str
    file_path: str
    source_s3_uri: str | None
    markdown_s3_uri: str | None
    file_type: str | None
    section_count: int | None
    parser_version: str | None
    caption_model: str | None
    embedding_model: str | None
    uploaded_at: str | None
    processed_at: str | None


class GetDocumentStatus:
    def __init__(self, document_repository: DocumentRepository) -> None:
        self._document_repository = document_repository

    def execute(self, doc_id: str) -> DocumentStatusResult | None:
        doc = self._document_repository.get_document(doc_id)
        if doc is None:
            return None
        return DocumentStatusResult(
            doc_id=doc.id,
            status=doc.status,
            file_path=doc.file_path,
            source_s3_uri=doc.source_s3_uri,
            markdown_s3_uri=doc.markdown_s3_uri,
            file_type=doc.file_type,
            section_count=doc.section_count,
            parser_version=doc.parser_version,
            caption_model=doc.caption_model,
            embedding_model=doc.embedding_model,
            uploaded_at=doc.uploaded_at.isoformat() if doc.uploaded_at else None,
            processed_at=doc.processed_at.isoformat() if doc.processed_at else None,
        )
