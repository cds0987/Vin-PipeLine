from __future__ import annotations

from config import settings
from models.ingest_job import ChunkResult
from retrieval.service import RetrievalService


class _AIProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    def ocr(self, image_bytes: bytes) -> str:
        return ""


class _VectorStore:
    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[ChunkResult]:
        return [
            ChunkResult(
                chunk_id="high",
                doc_id="doc-1",
                content="high score",
                metadata={"score": 0.8, "s3_uri": "s3://bucket/high.pdf"},
                page_start=1,
                page_end=1,
            ),
            ChunkResult(
                chunk_id="low",
                doc_id="doc-2",
                content="low score",
                metadata={"score": 0.2, "s3_uri": "s3://bucket/low.pdf"},
                page_start=2,
                page_end=2,
            ),
        ]

    def upsert(self, chunks: list[ChunkResult]) -> None:
        return None

    def delete(self, doc_id: str) -> None:
        return None


def test_retrieval_service_filters_low_scores(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.5)

    service = RetrievalService(
        ai_provider=_AIProvider(),
        vector_store=_VectorStore(),
    )

    results = service.search("policy", top_k=5)

    assert [item["chunk_id"] for item in results] == ["high"]


def test_search_threshold_default_is_enabled():
    assert settings.SEARCH_SCORE_THRESHOLD == 0.5
