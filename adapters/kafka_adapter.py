from __future__ import annotations

from models.ingest_job import IngestJob
from utils.mapper import map_document_uploaded_to_job
from utils.validator import validate_document_uploaded


class KafkaAdapter:
    def map(self, raw_event: dict) -> IngestJob | None:
        event = validate_document_uploaded(raw_event)
        if event is None:
            return None
        return map_document_uploaded_to_job(event)
