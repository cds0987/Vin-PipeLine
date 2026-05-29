"""
Adapter-specific fixtures.

Provides helpers for building fake S3 responses so scanner tests
don't need to repeat boto3 mock setup.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from utils.stores import InMemoryMetadataStore


def s3_obj(key: str, last_modified: datetime | None = None) -> dict:
    """Build a single fake S3 object dict as returned by list_objects_v2."""
    return {"Key": key, "LastModified": last_modified or datetime(2026, 1, 1, tzinfo=timezone.utc)}


def run_scan(objects: list[dict], store: InMemoryMetadataStore | None = None, prefix: str = "") -> list:
    """Run S3Scanner against a fake bucket page without touching real S3."""
    from adapters.s3_adapter import S3Scanner

    metadata_store = store or InMemoryMetadataStore()
    scanner = S3Scanner(metadata_store)

    fake_paginator = MagicMock()
    fake_paginator.paginate.return_value = [{"Contents": objects}]
    fake_client = MagicMock()
    fake_client.get_paginator.return_value = fake_paginator

    with patch("adapters.s3_adapter._s3_client", return_value=fake_client):
        return scanner.scan(bucket="test-bucket", prefix=prefix)


@pytest.fixture
def empty_store() -> InMemoryMetadataStore:
    return InMemoryMetadataStore()
