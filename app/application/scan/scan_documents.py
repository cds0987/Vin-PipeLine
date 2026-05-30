from __future__ import annotations

from app.domain.documents.models import IngestJob
from app.ports.scanning import SourceScanner


class ScanDocuments:
    def __init__(self, scanner: SourceScanner) -> None:
        self._scanner = scanner

    def execute(self, bucket: str | None = None, prefix: str | None = None) -> list[IngestJob]:
        return self._scanner.scan(bucket=bucket, prefix=prefix)
