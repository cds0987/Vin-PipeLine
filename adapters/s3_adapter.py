from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from config import settings
from models.ingest_job import IngestJob
from utils.stores import MetadataStore

log = logging.getLogger(__name__)

_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".html", ".htm",
                       ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}


def _uri_to_doc_id(s3_uri: str) -> str:
    # doc_id is derived from the S3 URI path, not file content.
    # Trade-off: re-uploading the same path re-indexes cleanly (no duplicate),
    # but renaming/moving a file creates a new doc_id and leaves the old record
    # stale in the DB.  S3 renames are rare; acceptable for this use case.
    return hashlib.md5(s3_uri.encode()).hexdigest()


def _s3_client():
    import boto3
    kwargs: dict = {"endpoint_url": settings.S3_ENDPOINT}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


class S3Scanner:
    """
    Quét S3 bucket để tìm file mới hoặc đã thay đổi.

    Logic:
    - file chưa có trong documents table → ingest
    - file có trong documents table nhưng S3 last_modified mới hơn s3_last_modified đã lưu → re-ingest
    - file đã indexed và không đổi → skip
    - file đang indexing → skip (tránh double-run)
    """

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

        jobs: list[IngestJob] = []
        paginator = client.get_paginator("list_objects_v2")

        try:
            pages = paginator.paginate(Bucket=bucket, Prefix=prefix)
        except Exception as exc:
            log.error("S3 list_objects failed bucket=%s prefix=%s: %s", bucket, prefix, exc)
            return []

        for page in pages:
            for obj in page.get("Contents", []):
                key: str = obj["Key"]
                if Path(key).suffix.lower() not in _SUPPORTED_SUFFIXES:
                    continue

                s3_uri = f"s3://{bucket}/{key}"
                s3_last_modified = obj["LastModified"]  # tz-aware datetime from S3
                file_name = Path(key).name

                existing = self._metadata_store.get_by_file_path(s3_uri)

                if existing is None:
                    log.info("S3Scanner: new file %s", s3_uri)
                    jobs.append(IngestJob(
                        doc_id=_uri_to_doc_id(s3_uri),
                        file_uri=s3_uri,
                        s3_last_modified=s3_last_modified,
                        metadata={"file_name": file_name},
                    ))
                elif existing.status == "indexing":
                    log.debug("S3Scanner: skipping %s — already indexing", s3_uri)
                elif existing.status in ("failed", "pending"):
                    log.info("S3Scanner: retry %s (status=%s)", s3_uri, existing.status)
                    jobs.append(IngestJob(
                        doc_id=existing.id,
                        file_uri=s3_uri,
                        s3_last_modified=s3_last_modified,
                        metadata={"file_name": file_name},
                    ))
                elif existing.s3_last_modified and s3_last_modified.replace(tzinfo=None) > existing.s3_last_modified.replace(tzinfo=None):
                    log.info("S3Scanner: file changed %s", s3_uri)
                    jobs.append(IngestJob(
                        doc_id=existing.id,
                        file_uri=s3_uri,
                        s3_last_modified=s3_last_modified,
                        metadata={"file_name": file_name},
                    ))
                else:
                    log.debug("S3Scanner: already indexed %s", s3_uri)

        log.info("S3Scanner: found %d file(s) to ingest from s3://%s/%s", len(jobs), bucket, prefix)
        return jobs
