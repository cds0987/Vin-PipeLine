"""
API-specific fixtures.

Provides a pre-indexed api_client fixture so tests that need data already in
the store don't have to repeat the ingest setup themselves.
"""
from __future__ import annotations

import pytest

from adapters.file_adapter import FileAdapter
from pipeline.run import run


@pytest.fixture
def indexed_api_client(api_client, fake_ai_provider, vector_store, metadata_store):
    """api_client with policy.txt already indexed — use when search results are needed."""
    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-preloaded")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)
    return api_client
