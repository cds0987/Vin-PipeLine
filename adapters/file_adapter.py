from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from models.ingest_job import IngestJob


class FileAdapter:
    def map(self, file_path: str, doc_id: str | None = None) -> IngestJob:
        file_name = Path(file_path).name
        return IngestJob(
            doc_id=doc_id or str(uuid4()),
            file_uri=file_path,
            file_name=file_name,
            metadata={"file_name": file_name},
        )
