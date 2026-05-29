from __future__ import annotations

import os
import uuid
from datetime import timezone

import boto3
import pytest

from adapters.s3_adapter import S3Scanner
from utils.stores import InMemoryMetadataStore

pytestmark = pytest.mark.minio


def _minio_endpoint() -> str:
    return os.getenv("MINIO_TEST_ENDPOINT", "http://minio:9000")


def _minio_bucket() -> str:
    return os.getenv("MINIO_TEST_BUCKET", "rag-pipeline-local")


@pytest.fixture
def minio_client():
    client = boto3.client(
        "s3",
        endpoint_url=_minio_endpoint(),
        aws_access_key_id=os.getenv("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
    )
    bucket = _minio_bucket()
    existing = {item["Name"] for item in client.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)
    return client


def test_scan_reads_real_objects_from_minio(monkeypatch, minio_client):
    bucket = _minio_bucket()
    prefix = f"it-{uuid.uuid4().hex}/"
    key = f"{prefix}contracts/sample.pdf"

    minio_client.put_object(Bucket=bucket, Key=key, Body=b"%PDF-1.4\n% integration-test\n")

    monkeypatch.setattr("config.settings.S3_BUCKET", bucket)
    monkeypatch.setattr("config.settings.SCAN_PREFIX", prefix)
    monkeypatch.setattr("config.settings.S3_ENDPOINT", _minio_endpoint())
    monkeypatch.setattr("config.settings.AWS_ACCESS_KEY_ID", os.getenv("MINIO_ROOT_USER", "minioadmin"))
    monkeypatch.setattr("config.settings.AWS_SECRET_ACCESS_KEY", os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"))

    jobs = S3Scanner(InMemoryMetadataStore()).scan()

    matching = [job for job in jobs if job.file_uri == f"s3://{bucket}/{key}"]
    assert len(matching) == 1
    assert matching[0].file_name == "sample.pdf"
    assert matching[0].document_type == "contracts"
    assert matching[0].s3_last_modified.astimezone(timezone.utc).tzinfo == timezone.utc
