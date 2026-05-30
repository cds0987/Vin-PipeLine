from __future__ import annotations

from adapters.s3_adapter import S3Scanner
from app.domain.documents.models import IngestJob
from app.ports.scanning import SourceScanner
from utils.stores import MetadataStore


class S3SourceScanner(SourceScanner):
    def __init__(self, metadata_store: MetadataStore) -> None:
        self._scanner = S3Scanner(metadata_store)

    def scan(self, bucket: str | None = None, prefix: str | None = None) -> list[IngestJob]:
        return [IngestJob(**job.model_dump()) for job in self._scanner.scan(bucket=bucket, prefix=prefix)]
