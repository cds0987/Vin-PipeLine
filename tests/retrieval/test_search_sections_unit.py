"""
Unit tests for the SearchSections application use case.

Tests the new SearchSections class directly (not via RetrievalService wrapper).

Covers:
  - Basic search returns results
  - Score threshold filtering
  - request_id forwarded to logging (accepted without error)
  - Query embedding cache (hit / miss)
  - Top-k limit respected
  - SectionSearchResult fields populated correctly
"""
from __future__ import annotations

from app.application.search.search_sections import SearchSections
from app.domain.documents.models import SectionRecord


class _FakeEmbedder:
    def __init__(self, dim: int = 4) -> None:
        self.call_count = 0
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
        return [[float(i) / 10 for i in range(self._dim)] for _ in texts]


class _FakeSectionIndex:
    def __init__(self, sections: list[SectionRecord]) -> None:
        self._sections = sections

    def search_sections(self, vector: list[float], top_k: int) -> list[SectionRecord]:
        return self._sections[:top_k]

    def upsert_sections(self, sections): pass
    def delete_document(self, doc_id): pass


def _section(
    section_id: str = "s1",
    doc_id: str = "doc1",
    score: float = 0.9,
    **kwargs,
) -> SectionRecord:
    return SectionRecord(
        section_id=section_id,
        doc_id=doc_id,
        section_content="content",
        caption="caption",
        markdown_s3_uri="s3://bucket/md/doc1.md",
        source_s3_uri="s3://bucket/raw/doc1.pdf",
        metadata={"score": score, "file_name": "doc1.pdf"},
        **kwargs,
    )


# ─── basic search ─────────────────────────────────────────────────────────────

def test_search_returns_section_search_results(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    index = _FakeSectionIndex([_section()])
    use_case = SearchSections(_FakeEmbedder(), index)

    results = use_case.search("any query", top_k=5)

    assert len(results) == 1
    assert results[0].section_id == "s1"
    assert results[0].document_id == "doc1"


def test_search_result_has_required_fields(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    index = _FakeSectionIndex([_section()])
    use_case = SearchSections(_FakeEmbedder(), index)

    result = use_case.search("query")[0]

    assert result.caption == "caption"
    assert result.section_content == "content"
    assert result.markdown_s3_uri == "s3://bucket/md/doc1.md"
    assert result.source_s3_uri == "s3://bucket/raw/doc1.pdf"
    assert isinstance(result.score, float)


# ─── threshold filtering ──────────────────────────────────────────────────────

def test_search_filters_below_threshold(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.5)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", 256)
    index = _FakeSectionIndex([
        _section("high", score=0.8),
        _section("low", score=0.2),
    ])
    use_case = SearchSections(_FakeEmbedder(), index)

    results = use_case.search("query", top_k=10)

    assert len(results) == 1
    assert results[0].section_id == "high"


def test_search_threshold_zero_returns_all(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    index = _FakeSectionIndex([_section("a", score=0.1), _section("b", score=0.9)])
    use_case = SearchSections(_FakeEmbedder(), index)

    results = use_case.search("query", top_k=10)

    assert len(results) == 2


# ─── request_id parameter ─────────────────────────────────────────────────────

def test_search_accepts_request_id_without_error(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    index = _FakeSectionIndex([_section()])
    use_case = SearchSections(_FakeEmbedder(), index)

    results = use_case.search("query", top_k=5, request_id="req-abc-123")

    assert len(results) == 1


def test_search_works_without_request_id(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    index = _FakeSectionIndex([_section()])
    use_case = SearchSections(_FakeEmbedder(), index)

    results = use_case.search("query", top_k=5)  # no request_id

    assert len(results) == 1


# ─── query embedding cache ────────────────────────────────────────────────────

def test_same_query_uses_cached_embedding(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", 10)
    embedder = _FakeEmbedder()
    use_case = SearchSections(embedder, _FakeSectionIndex([]))

    use_case.search("same query")
    use_case.search("same query")
    use_case.search("same query")

    assert embedder.call_count == 1


def test_different_queries_each_call_embed(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    monkeypatch.setattr("config.settings.SEARCH_QUERY_CACHE_SIZE", 10)
    embedder = _FakeEmbedder()
    use_case = SearchSections(embedder, _FakeSectionIndex([]))

    use_case.search("query A")
    use_case.search("query B")
    use_case.search("query C")

    assert embedder.call_count == 3


# ─── top-k limit ─────────────────────────────────────────────────────────────

def test_search_respects_top_k(monkeypatch):
    monkeypatch.setattr("config.settings.SEARCH_SCORE_THRESHOLD", 0.0)
    sections = [_section(f"s{i}", score=0.9) for i in range(10)]
    use_case = SearchSections(_FakeEmbedder(), _FakeSectionIndex(sections))

    results = use_case.search("query", top_k=3)

    assert len(results) == 3
