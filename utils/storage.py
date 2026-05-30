from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from config import settings
from models.ingest_job import MarkdownDocument


def _s3_client():
    import boto3

    kwargs: dict = {"endpoint_url": settings.S3_ENDPOINT}
    if settings.AWS_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
    if settings.AWS_SECRET_ACCESS_KEY:
        kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def _ensure_allowed_bucket(bucket: str, *, purpose: str = "source") -> None:
    allowed = {settings.S3_BUCKET}
    if purpose in {"markdown", "read_text"}:
        allowed.add(settings.MARKDOWN_BUCKET)
    if bucket not in allowed:
        raise ValueError(f"Cross-bucket access denied for {purpose}: {bucket}")


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


def _s3_bucket_and_key(file_uri: str, *, purpose: str = "source") -> tuple[str, str]:
    parsed = urlparse(file_uri)
    bucket = parsed.netloc or settings.S3_BUCKET
    key = parsed.path.lstrip("/")
    _ensure_allowed_bucket(bucket, purpose=purpose)
    if not key:
        raise ValueError(f"Invalid S3 URI without object key: {file_uri}")
    return bucket, key


def _read_s3_bytes(file_uri: str) -> bytes:
    bucket, key = _s3_bucket_and_key(file_uri, purpose="source")
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


def _write_s3_text(file_uri: str, payload: str) -> str:
    bucket, key = _s3_bucket_and_key(file_uri, purpose="markdown")
    client = _s3_client()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=payload.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )
    return f"s3://{bucket}/{key}"


def _write_local_text(file_uri: str, payload: str) -> str:
    path = Path(file_uri)
    _ensure_within_root(path)
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(payload, encoding="utf-8")
    return str(resolved)


def _markdown_local_path(doc_id: str) -> Path:
    return (settings.DATA_DIR / "derived" / "markdown" / f"{doc_id}.md").resolve()


def build_markdown_uri(doc_id: str) -> str:
    if settings.USE_S3:
        return f"s3://{settings.MARKDOWN_BUCKET}/{settings.MARKDOWN_S3_PREFIX.strip('/')}/{doc_id}.md"
    return str(_markdown_local_path(doc_id))


def write_markdown(doc: MarkdownDocument) -> MarkdownDocument:
    target_uri = doc.markdown_s3_uri or build_markdown_uri(doc.doc_id)
    if target_uri.startswith("s3://"):
        persisted_uri = _write_s3_text(target_uri, doc.markdown_content)
    else:
        persisted_uri = _write_local_text(target_uri, doc.markdown_content)
    return doc.model_copy(update={"markdown_s3_uri": persisted_uri})


def read_text(file_uri: str) -> str:
    if file_uri.startswith("s3://"):
        bucket, key = _s3_bucket_and_key(file_uri, purpose="read_text")
        client = _s3_client()
        obj = client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode("utf-8", errors="ignore")
    path = Path(file_uri)
    _ensure_within_root(path)
    return path.resolve().read_text(encoding="utf-8")


def write_dlq_file(file_name: str, payload: str) -> Path:
    target = Path(settings.get_path("dlq")) / file_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload, encoding="utf-8")
    return target
