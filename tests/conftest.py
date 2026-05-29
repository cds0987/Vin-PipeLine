from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

from utils.stores import FileMetadataStore, InMemoryVectorStore


class FakeAIProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text.split())), 1.0, 0.5] for text in texts]

    def ocr(self, image_bytes: bytes) -> str:
        return "ocr text"


@pytest.fixture
def fake_ai_provider() -> FakeAIProvider:
    return FakeAIProvider()


@pytest.fixture
def vector_store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def metadata_store(tmp_path) -> FileMetadataStore:
    return FileMetadataStore(base_dir=str(tmp_path / "store"))


@pytest.fixture
def api_client(monkeypatch, fake_ai_provider, vector_store, metadata_store):
    import api.main as api_main

    monkeypatch.setattr(api_main, "build_ai_provider", lambda: fake_ai_provider)
    monkeypatch.setattr(api_main, "build_vector_store", lambda: vector_store)
    monkeypatch.setattr(api_main, "build_metadata_store", lambda: metadata_store)

    with TestClient(api_main.app) as client:
        yield client
