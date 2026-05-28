from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from config import settings


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


def _read_s3_bytes(file_uri: str) -> bytes:
    parsed = urlparse(file_uri)
    bucket = parsed.netloc or settings.S3_BUCKET
    key = parsed.path.lstrip("/")
    obj = _s3_client().get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()


def _read_local_bytes(file_uri: str) -> bytes:
    return Path(file_uri).read_bytes()


def read_binary(file_uri: str) -> bytes:
    if file_uri.startswith("s3://"):
        return _read_s3_bytes(file_uri)
    return _read_local_bytes(file_uri)


def write_dlq_file(file_name: str, payload: str) -> Path:
    target = Path(settings.get_path("dlq")) / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return target
