from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from config import settings


def _s3_client():
    import boto3

    kwargs: dict = {"endpoint_url": settings.S3_ENDPOINT}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def _ensure_allowed_bucket(bucket: str) -> None:
    if bucket != settings.S3_BUCKET:
        raise ValueError(f"Cross-bucket access denied: {bucket}")


def _ensure_within_root(path: Path) -> None:
    resolved = path.resolve()
    allowed_root = settings.LOCAL_FILE_ROOT
    if not resolved.is_relative_to(allowed_root):
        raise ValueError(f"Path traversal denied: {resolved}")


def _validate_size(size_bytes: int, file_uri: str) -> None:
    if size_bytes > settings.MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File exceeds MAX_FILE_SIZE_BYTES ({size_bytes} > {settings.MAX_FILE_SIZE_BYTES}): {file_uri}"
        )


def _s3_bucket_and_key(file_uri: str) -> tuple[str, str]:
    parsed = urlparse(file_uri)
    bucket = parsed.netloc or settings.S3_BUCKET
    key = parsed.path.lstrip("/")
    _ensure_allowed_bucket(bucket)
    if not key:
        raise ValueError(f"Invalid S3 URI without object key: {file_uri}")
    return bucket, key


def _read_s3_bytes(file_uri: str) -> bytes:
    bucket, key = _s3_bucket_and_key(file_uri)
    client = _s3_client()
    head = client.head_object(Bucket=bucket, Key=key)
    _validate_size(int(head.get("ContentLength", 0)), file_uri)
    obj = client.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read()


def _read_local_bytes(file_uri: str) -> bytes:
    path = Path(file_uri)
    _ensure_within_root(path)
    resolved = path.resolve()
    _validate_size(resolved.stat().st_size, file_uri)
    return resolved.read_bytes()


def read_binary(file_uri: str) -> bytes:
    if file_uri.startswith("s3://"):
        return _read_s3_bytes(file_uri)
    return _read_local_bytes(file_uri)


def write_dlq_file(file_name: str, payload: str) -> Path:
    target = Path(settings.get_path("dlq")) / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return target
