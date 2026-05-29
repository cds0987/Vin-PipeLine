from __future__ import annotations

from models.events import DocumentUploaded
from models.ingest_job import IngestJob


def map_document_uploaded_to_job(event: DocumentUploaded) -> IngestJob:
    metadata = event.metadata.model_dump(exclude_none=True)
    return IngestJob(
        doc_id=event.doc_id,
        file_uri=event.s3_uri,
        language=metadata.get("language", "vi"),
        document_type=metadata.get("document_type", "general"),
        metadata=metadata,
    )
