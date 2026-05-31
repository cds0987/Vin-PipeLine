from __future__ import annotations

import importlib

import pytest

from config import settings
from models.ingest_job import ChunkResult

embed = importlib.import_module("pipeline.04_embed")


class _RecordingProvider:
    """Records every embed() call; returns vectors of fixed dimension."""

    def __init__(self, dim: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.caption_calls: list[list[str]] = []
        self._dim = dim or settings.EMBEDDING_DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(i) / 10 for i in range(self._dim)] for _ in texts]

    def caption(self, texts: list[str]) -> list[str]:
        self.caption_calls.append(list(texts))
        return [f"caption::{text}" for text in texts]

    def ocr(self, image_bytes: bytes) -> str:
        return ""

    def get_llm_client(self):
        return None


def _chunk(idx: int) -> ChunkResult:
    return ChunkResult(
        section_id=f"doc_section_{idx:04d}",
        doc_id="doc",
        section_content=f"section content {idx}",
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


def test_caption_model_name_stamped_in_metadata(monkeypatch):
    monkeypatch.setattr("config.settings.CAPTION_MODEL", "test-caption-model")
    provider = _RecordingProvider()
    result = embed.run([_chunk(0)], provider)
    assert result[0].metadata["caption_model"] == "test-caption-model"


# ─── batch processing (BatchEmbedder coalesces into one provider call) ────────

def test_multiple_chunks_coalesced_into_single_provider_call():
    """BatchEmbedder collects all sections and calls provider once per flush."""
    provider = _RecordingProvider()
    embed.run([_chunk(i) for i in range(5)], provider, batch_size=2)
    # All 5 sections fit within EMBED_MAX_BATCH_SIZE — flushed in one call
    assert len(provider.calls) == 1
    assert len(provider.calls[0]) == 5


def test_all_chunks_receive_embeddings():
    provider = _RecordingProvider(dim=settings.EMBEDDING_DIM)
    chunks = [_chunk(i) for i in range(10)]
    result = embed.run(chunks, provider, batch_size=3)
    for chunk in result:
        assert len(chunk.embedding) == settings.EMBEDDING_DIM


# ─── provider receives correct texts ─────────────────────────────────────────

def test_provider_receives_caption_strings_for_embedding():
    provider = _RecordingProvider()
    chunks = [_chunk(i) for i in range(3)]
    embed.run(chunks, provider, batch_size=10)
    all_texts = [t for batch in provider.calls for t in batch]
    assert all_texts == [c.caption for c in chunks]


def test_caption_provider_receives_section_content_strings():
    """AISectionCaptioner captions each section individually (one text per call)."""
    provider = _RecordingProvider()
    chunks = [_chunk(i) for i in range(3)]
    embed.run(chunks, provider, batch_size=10)
    # Caption is called once per section (asyncio.gather + _caption_one)
    all_texts = [t for batch in provider.caption_calls for t in batch]
    assert all_texts == [c.section_content for c in chunks]


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


# ─── error cases ──────────────────────────────────────────────────────────────

def test_embedding_response_size_mismatch_raises():
    """Provider returning wrong number of embeddings must raise ValueError."""
    class _ShortProvider:
        def embed(self, texts):
            return [[0.1] * settings.EMBEDDING_DIM]  # only 1 instead of 3
        def caption(self, texts): return texts
        def ocr(self, _): return ""
        def get_llm_client(self): return None

    with pytest.raises(ValueError, match="Embedding response size mismatch"):
        embed.run([_chunk(i) for i in range(3)], _ShortProvider())


def test_embedding_dimension_mismatch_raises(monkeypatch):
    """Embedding with wrong dimension must raise ValueError."""
    monkeypatch.setattr("config.settings.EMBEDDING_DIM", 8)

    class _WrongDimProvider:
        def embed(self, texts):
            return [[0.1] * 4 for _ in texts]   # 4 dims instead of 8
        def caption(self, texts): return texts
        def ocr(self, _): return ""
        def get_llm_client(self): return None

    with pytest.raises(ValueError, match="Embedding dimension mismatch"):
        embed.run([_chunk(0)], _WrongDimProvider())


def test_dimension_mismatch_message_includes_section_id(monkeypatch):
    monkeypatch.setattr("config.settings.EMBEDDING_DIM", 8)

    class _WrongDimProvider:
        def embed(self, texts): return [[0.1] * 2 for _ in texts]
        def caption(self, texts): return texts
        def ocr(self, _): return ""
        def get_llm_client(self): return None

    chunk = _chunk(42)
    with pytest.raises(ValueError) as exc_info:
        embed.run([chunk], _WrongDimProvider())
    assert chunk.section_id in str(exc_info.value)
