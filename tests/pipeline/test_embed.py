from __future__ import annotations

import importlib

from config import settings
from models.ingest_job import ChunkResult

embed = importlib.import_module("pipeline.04_embed")


class _RecordingProvider:
    """Records every embed() call; returns vectors of fixed dimension."""

    def __init__(self, dim: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self._dim = dim or settings.EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(i) / 10 for i in range(self._dim)] for _ in texts]

    def ocr(self, image_bytes: bytes) -> str:
        return ""


def _chunk(idx: int) -> ChunkResult:
    return ChunkResult(
        chunk_id=f"doc_chunk_{idx:04d}",
        doc_id="doc",
        content=f"chunk content {idx}",
    )


# ─── empty input ──────────────────────────────────────────────────────────────

def test_empty_list_returns_empty_and_never_calls_provider():
    provider = _RecordingProvider()
    result = embed.run([], provider)
    assert result == []
    assert provider.calls == []


# ─── single chunk ─────────────────────────────────────────────────────────────

def test_single_chunk_receives_embedding():
    provider = _RecordingProvider(dim=settings.EMBEDDING_DIM)
    result = embed.run([_chunk(0)], provider)
    assert len(result) == 1
    assert len(result[0].embedding) == settings.EMBEDDING_DIM


# ─── embedding model stamped in metadata ──────────────────────────────────────

def test_embedding_model_name_stamped_in_metadata(monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MODEL", "test-embed-model")
    provider = _RecordingProvider()
    result = embed.run([_chunk(0)], provider)
    assert result[0].metadata["embedding_model"] == "test-embed-model"


# ─── batch processing ─────────────────────────────────────────────────────────

def test_5_chunks_with_batch_size_2_makes_3_provider_calls():
    """Batches: [0,1] [2,3] [4] → 3 calls."""
    provider = _RecordingProvider()
    embed.run([_chunk(i) for i in range(5)], provider, batch_size=2)
    assert len(provider.calls) == 3
    assert len(provider.calls[0]) == 2
    assert len(provider.calls[1]) == 2
    assert len(provider.calls[2]) == 1


def test_chunks_exactly_divisible_by_batch_size():
    """4 chunks, batch_size=2 → exactly 2 calls."""
    provider = _RecordingProvider()
    embed.run([_chunk(i) for i in range(4)], provider, batch_size=2)
    assert len(provider.calls) == 2


def test_all_chunks_receive_embeddings_across_batches():
    provider = _RecordingProvider(dim=settings.EMBEDDING_DIM)
    chunks = [_chunk(i) for i in range(10)]
    result = embed.run(chunks, provider, batch_size=3)
    for chunk in result:
        assert len(chunk.embedding) == settings.EMBEDDING_DIM


# ─── provider receives correct texts ─────────────────────────────────────────

def test_provider_receives_chunk_content_strings():
    provider = _RecordingProvider()
    chunks = [_chunk(i) for i in range(3)]
    embed.run(chunks, provider, batch_size=10)
    all_texts = [t for batch in provider.calls for t in batch]
    assert all_texts == [c.content for c in chunks]


# ─── mutates in place ─────────────────────────────────────────────────────────

def test_run_returns_same_list_reference():
    provider = _RecordingProvider()
    chunks = [_chunk(0)]
    result = embed.run(chunks, provider)
    assert result is chunks


def test_embedding_written_back_to_original_objects():
    provider = _RecordingProvider(dim=settings.EMBEDDING_DIM)
    chunk = _chunk(0)
    embed.run([chunk], provider)
    assert len(chunk.embedding) == settings.EMBEDDING_DIM


# ─── batch_size larger than chunk count ───────────────────────────────────────

def test_batch_size_larger_than_total_makes_single_call():
    provider = _RecordingProvider()
    embed.run([_chunk(i) for i in range(3)], provider, batch_size=100)
    assert len(provider.calls) == 1
    assert len(provider.calls[0]) == 3
