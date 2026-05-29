from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from config import settings
from utils.stores import InMemoryMetadataStore, InMemoryVectorStore


class FakeAIProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            base = float(len(text.split()) or 1)
            vector = [0.0] * settings.EMBEDDING_DIM
            vector[0] = base
            vector[1] = 1.0
            vector[2] = 0.5
            embeddings.append(vector)
        return embeddings

    def ocr(self, image_bytes: bytes) -> str:
        return "ocr text"


@pytest.fixture
def fake_ai_provider() -> FakeAIProvider:
    return FakeAIProvider()


@pytest.fixture
def vector_store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def metadata_store() -> InMemoryMetadataStore:
    return InMemoryMetadataStore()


@pytest.fixture
def tmp_path():
    base_root = Path(".test_tmp")
    base_root.mkdir(parents=True, exist_ok=True)
    path = base_root / f"case-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def api_client(monkeypatch, fake_ai_provider, vector_store, metadata_store):
    import api.main as api_main

    monkeypatch.setattr(api_main, "build_ai_provider", lambda: (fake_ai_provider, None))
    monkeypatch.setattr(api_main, "build_vector_store", lambda: (vector_store, None))
    monkeypatch.setattr(api_main, "build_metadata_store", lambda: (metadata_store, None))

    with TestClient(api_main.app) as client:
        yield client
