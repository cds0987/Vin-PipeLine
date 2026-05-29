"""
Integration tests against Qdrant Cloud.
Chỉ chạy khi có kết nối thực: pytest -m integration -v
CI job: qdrant-integration (dùng QDRANT_URL + QDRANT_API_KEY từ GitHub Secrets)
"""
from __future__ import annotations

import pytest

from config import settings
from models.ingest_job import ChunkResult

pytestmark = pytest.mark.integration


def _make_embedding(seed: int = 0) -> list[float]:
    dim = settings.EMBEDDING_DIM
    return [((seed + i) % 255) / 255.0 for i in range(dim)]


def _make_chunk(doc_id: str, idx: int, content: str) -> ChunkResult:
    return ChunkResult(
        chunk_id=f"{doc_id}_chunk_{idx:04d}",
        doc_id=doc_id,
        content=content,
        embedding=_make_embedding(idx),
        metadata={"chunk_index": idx},
    )


@pytest.fixture(scope="module")
def store():
    from utils.stores import QdrantStore

    s = QdrantStore()
    yield s
    # teardown — xóa toàn bộ doc test khỏi collection
    for doc_id in ("ci-doc-a", "ci-doc-b"):
        try:
            s.delete(doc_id)
        except Exception:
            pass


def test_upsert_and_search(store):
    chunks = [_make_chunk("ci-doc-a", 0, "Qdrant Cloud integration test — upsert")]
    store.upsert(chunks)

    results = store.search(_make_embedding(0), top_k=10)
    assert any(r.doc_id == "ci-doc-a" for r in results)


def test_search_returns_correct_fields(store):
    results = store.search(_make_embedding(0), top_k=10)
    hit = next((r for r in results if r.doc_id == "ci-doc-a"), None)

    assert hit is not None
    assert hit.chunk_id == "ci-doc-a_chunk_0000"
    assert "Qdrant Cloud" in hit.content
    assert isinstance(hit.metadata.get("score"), float)


def test_idempotent_upsert(store):
    updated = _make_chunk("ci-doc-a", 0, "Updated content — idempotent upsert")
    store.upsert([updated])

    results = store.search(_make_embedding(0), top_k=20)
    hits = [r for r in results if r.doc_id == "ci-doc-a"]

    assert len(hits) == 1, "Upsert cùng chunk_id không được tạo duplicate"
    assert hits[0].content == "Updated content — idempotent upsert"


def test_delete_removes_doc(store):
    store.upsert([_make_chunk("ci-doc-b", 0, "sẽ bị xóa")])
    store.delete("ci-doc-b")

    results = store.search(_make_embedding(0), top_k=20)
    assert not any(r.doc_id == "ci-doc-b" for r in results)
