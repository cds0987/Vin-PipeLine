from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from models.ingest_job import DocumentRecord, IngestJob
from utils.stores import MetadataStore

log = logging.getLogger(__name__)

_SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tiff",
}


def _uri_to_doc_id(s3_uri: str) -> str:
    # doc_id is derived from the S3 URI path, not file content.
    # Trade-off: re-uploading the same path re-indexes cleanly (no duplicate),
    # but renaming/moving a file creates a new doc_id and leaves the old record
    # stale in the DB. S3 renames are rare; acceptable for this use case.
    return hashlib.md5(s3_uri.encode()).hexdigest()


def _s3_client():
    import boto3

    kwargs: dict = {"endpoint_url": settings.S3_ENDPOINT}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def _is_stale_indexing(existing: DocumentRecord) -> bool:
    if existing.status != "indexing":
        return False
    if settings.STALE_INDEXING_SECONDS == 0:
        return True
    updated_at = existing.updated_at or existing.uploaded_at
    age_seconds = (datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc)).total_seconds()
    return age_seconds >= settings.STALE_INDEXING_SECONDS


class S3Scanner:
    """Scan S3 for new or changed files."""

    def __init__(self, metadata_store: MetadataStore) -> None:
        self._metadata_store = metadata_store

    def scan(self, bucket: str | None = None, prefix: str | None = None) -> list[IngestJob]:
        bucket = bucket or settings.S3_BUCKET
        prefix = prefix if prefix is not None else settings.SCAN_PREFIX

        try:
            client = _s3_client()
        except Exception as exc:
            log.error("S3 client init failed: %s", exc)
            return []

        paginator = client.get_paginator("list_objects_v2")
        try:
            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
        except Exception as exc:
            log.error("S3 list_objects failed bucket=%s prefix=%s: %s", bucket, prefix, exc)
            return []

        discovered: list[tuple[str, str, datetime, str]] = []
        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if Path(key).suffix.lower() not in _SUPPORTED_SUFFIXES:
                    continue
                discovered.append(
                    (
                        key,
                        f"s3://{bucket}/{key}",
                        obj["LastModified"],
                        Path(key).name,
                    )
                )

        existing_by_path = self._metadata_store.get_by_file_paths([item[1] for item in discovered])
        jobs: list[IngestJob] = []

        for _key, s3_uri, s3_last_modified, file_name in discovered:
            existing = existing_by_path.get(s3_uri)
            if existing is None:
                log.info("S3Scanner: new file %s", s3_uri)
                jobs.append(
                    IngestJob(
                        doc_id=_uri_to_doc_id(s3_uri),
                        file_uri=s3_uri,
                        s3_last_modified=s3_last_modified,
                        metadata={"file_name": file_name},
                    )
                )
                continue

            if existing.status == "indexing" and not _is_stale_indexing(existing):
                log.debug("S3Scanner: skipping %s - already indexing", s3_uri)
                continue

            if existing.status in {"failed", "pending"} or _is_stale_indexing(existing):
                log.info("S3Scanner: retry %s (status=%s)", s3_uri, existing.status)
                jobs.append(
                    IngestJob(
                        doc_id=existing.id,
                        file_uri=s3_uri,
                        s3_last_modified=s3_last_modified,
                        metadata={"file_name": file_name},
                    )
                )
                continue

            if existing.s3_last_modified and (
                s3_last_modified.astimezone(timezone.utc)
                > existing.s3_last_modified.astimezone(timezone.utc)
            ):
                log.info("S3Scanner: file changed %s", s3_uri)
                jobs.append(
                    IngestJob(
                        doc_id=existing.id,
                        file_uri=s3_uri,
                        s3_last_modified=s3_last_modified,
                        metadata={"file_name": file_name},
                    )
                )
                continue

            log.debug("S3Scanner: already indexed %s", s3_uri)

        log.info("S3Scanner: found %d file(s) to ingest from s3://%s/%s", len(jobs), bucket, prefix)
        return jobs
