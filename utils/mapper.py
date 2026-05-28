from __future__ import annotations

from models.events import DocumentUploaded
from models.ingest_job import IngestJob, PermissionModel


def map_document_uploaded_to_job(event: DocumentUploaded) -> IngestJob:
    permission = event.permission or PermissionModel(
        visibility="private",
        owner_id=event.uploaded_by,
        org_id=event.org_id,
    )
    metadata = event.metadata.model_dump(exclude_none=True)
    return IngestJob(
        doc_id=event.doc_id,
        file_uri=event.s3_uri,
        language=metadata.get("language", "vi"),
        document_type=metadata.get("document_type", "general"),
        permission=permission,
        metadata=metadata,
    )
