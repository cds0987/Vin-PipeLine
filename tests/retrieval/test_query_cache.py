"""
Tests for RetrievalService query embedding cache.

Cache behaviour:
  - Hit: same query → embed() not called again, same vector reused
  - Miss: new query → embed() called
  - Eviction: when cache exceeds SEARCH_QUERY_CACHE_SIZE, oldest entry removed
  - LRU: recently used entries survive eviction
"""
from __future__ import annotations

import pytest

from retrieval.service import RetrievalService


class _CountingAI:
    def __init__(self, dim: int = 4) -> None:
        self.call_count = 0
        self._dim = dim
        self._vectors: dict[str, list[float]] = {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        results = []
        for t in texts:
            if t not in self._vectors:
                self._vectors[t] = [float(i + len(self._vectors)) for i in range(self._dim)]
            results.append(self._vectors[t])
        return results

    def ocr(self, _): return ""
    def get_llm_client(self): return None


class _EmptyVectorStore:
    def search(self, vector, top_k, filters=None): return []
    def upsert(self, chunks): pass
    def delete(self, doc_id): pass


# ── cache hit ─────────────────────────────────────────────────────────────────

def test_same_query_uses_cached_embedding(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", 10)

    ai = _CountingAI()
    service = RetrievalService(ai_provider=ai, vector_store=_EmptyVectorStore())

    service.search("policy document", top_k=3)
    service.search("policy document", top_k=3)
    service.search("policy document", top_k=3)

    assert ai.call_count == 1


def test_different_queries_each_call_embed(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", 10)

    ai = _CountingAI()
    service = RetrievalService(ai_provider=ai, vector_store=_EmptyVectorStore())

    service.search("policy A", top_k=3)
    service.search("policy B", top_k=3)
    service.search("policy C", top_k=3)

    assert ai.call_count == 3


# ── cache eviction ────────────────────────────────────────────────────────────

def test_cache_evicts_oldest_entry_when_full(monkeypatch):
    cache_size = 3
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", cache_size)

    ai = _CountingAI()
    service = RetrievalService(ai_provider=ai, vector_store=_EmptyVectorStore())

    # Fill cache: queries q0, q1, q2
    for i in range(cache_size):
        service.search(f"query {i}", top_k=1)

    assert ai.call_count == cache_size

    # Add a new query (q3) → q0 evicted
    service.search("query 3", top_k=1)
    assert ai.call_count == cache_size + 1

    # q0 was evicted → must re-embed
    service.search("query 0", top_k=1)
    assert ai.call_count == cache_size + 2


def test_cache_size_one_always_evicts(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", 1)

    ai = _CountingAI()
    service = RetrievalService(ai_provider=ai, vector_store=_EmptyVectorStore())

    service.search("first query", top_k=1)   # miss → embed
    service.search("second query", top_k=1)  # miss → embed, evicts "first query"
    service.search("first query", top_k=1)   # miss again → embed

    assert ai.call_count == 3


# ── LRU: recently used survives eviction ─────────────────────────────────────

def test_recently_accessed_entry_not_evicted(monkeypatch):
    cache_size = 3
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", cache_size)

    ai = _CountingAI()
    service = RetrievalService(ai_provider=ai, vector_store=_EmptyVectorStore())

    # Fill cache
    service.search("q0", top_k=1)
    service.search("q1", top_k=1)
    service.search("q2", top_k=1)
    assert ai.call_count == 3

    # Re-access q0 → moves to front (most recently used)
    service.search("q0", top_k=1)
    assert ai.call_count == 3  # cache hit

    # Add q3 → q1 evicted (oldest not-recently-used)
    service.search("q3", top_k=1)
    assert ai.call_count == 4

    # q0 should still be in cache (was recently used)
    service.search("q0", top_k=1)
    assert ai.call_count == 4  # still cached

    # q1 was evicted → must re-embed
    service.search("q1", top_k=1)
    assert ai.call_count == 5


# ── cache returns consistent results ─────────────────────────────────────────

def test_cache_hit_returns_same_vector_to_vector_store(monkeypatch):
    """Cached embedding must produce same search results as fresh embedding."""
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", 10)

    queried_vectors: list[list[float]] = []

    class _CapturingStore:
        def search(self, vector, top_k, filters=None):
            queried_vectors.append(list(vector))
            return []
        def upsert(self, chunks): pass
        def delete(self, doc_id): pass

    ai = _CountingAI(dim=4)
    service = RetrievalService(ai_provider=ai, vector_store=_CapturingStore())

    service.search("consistent query", top_k=3)
    service.search("consistent query", top_k=3)

    assert queried_vectors[0] == queried_vectors[1]
    assert ai.call_count == 1
