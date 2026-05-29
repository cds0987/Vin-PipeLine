"""
In-memory store tests — covers gaps not present in existing tests:
  - _cosine_similarity edge cases (zero, orthogonal, opposite, mismatched lengths)
  - InMemoryVectorStore: top_k, score ordering, filter by doc_id, delete, upsert idempotency
  - InMemoryMetadataStore: upsert replace, update_status creates stub, get_by_file_path
"""
from __future__ import annotations

from datetime import datetime, timezone

from models.ingest_job import ChunkResult, DocumentRecord
from utils.stores import InMemoryMetadataStore, InMemoryVectorStore, _cosine_similarity


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _chunk(chunk_id: str, doc_id: str, vec: list[float], content: str = "c") -> ChunkResult:
    return ChunkResult(chunk_id=chunk_id, doc_id=doc_id, content=content, embedding=vec)


def _doc(doc_id: str, status: str = "indexed", file_path: str = "s3://b/f.pdf") -> DocumentRecord:
    now = datetime.now(timezone.utc)
    return DocumentRecord(id=doc_id, file_path=file_path, status=status,
                          uploaded_at=now, updated_at=now)


# ─── _cosine_similarity ───────────────────────────────────────────────────────

def test_cosine_identical_vectors_is_one():
    v = [1.0, 0.0, 0.0]
    assert abs(_cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_orthogonal_vectors_is_zero():
    assert abs(_cosine_similarity([1.0, 0.0], [0.0, 1.0])) < 1e-9


def test_cosine_opposite_vectors_is_minus_one():
    assert abs(_cosine_similarity([1.0, 0.0], [-1.0, 0.0]) + 1.0) < 1e-9


def test_cosine_zero_vector_returns_zero():
    assert _cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert _cosine_similarity([1.0, 0.0], [0.0, 0.0]) == 0.0


def test_cosine_mismatched_lengths_returns_zero():
    assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0


def test_cosine_empty_vectors_returns_zero():
    assert _cosine_similarity([], []) == 0.0


def test_cosine_symmetry():
    a, b = [0.6, 0.8], [0.8, 0.6]
    assert abs(_cosine_similarity(a, b) - _cosine_similarity(b, a)) < 1e-9


# ─── InMemoryVectorStore — basic ──────────────────────────────────────────────

def test_upsert_and_search_finds_chunk():
    store = InMemoryVectorStore()
    store.upsert([_chunk("c1", "doc1", [1.0, 0.0])])
    results = store.search([1.0, 0.0], top_k=5)
    assert any(r.chunk_id == "c1" for r in results)


def test_empty_store_returns_empty():
    assert InMemoryVectorStore().search([1.0, 0.0], top_k=5) == []


def test_search_respects_top_k_limit():
    store = InMemoryVectorStore()
    for i in range(10):
        store.upsert([_chunk(f"c{i}", "doc1", [float(i), 0.0])])
    assert len(store.search([1.0, 0.0], top_k=3)) == 3


def test_search_results_ordered_by_score_descending():
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("exact", "doc1", [1.0, 0.0]),
        _chunk("ortho", "doc1", [0.0, 1.0]),
    ])
    results = store.search([1.0, 0.0], top_k=2)
    scores = [r.metadata.get("score", 0.0) for r in results]
    assert scores == sorted(scores, reverse=True)


def test_search_attaches_score_to_metadata():
    store = InMemoryVectorStore()
    store.upsert([_chunk("c1", "doc1", [1.0, 0.0])])
    results = store.search([1.0, 0.0], top_k=1)
    assert isinstance(results[0].metadata.get("score"), float)


# ─── InMemoryVectorStore — upsert overwrites ─────────────────────────────────

def test_upsert_same_chunk_id_overwrites():
    store = InMemoryVectorStore()
    store.upsert([_chunk("c1", "doc1", [1.0, 0.0], content="original")])
    store.upsert([_chunk("c1", "doc1", [1.0, 0.0], content="updated")])
    results = store.search([1.0, 0.0], top_k=5)
    matching = [r for r in results if r.chunk_id == "c1"]
    assert len(matching) == 1
    assert matching[0].content == "updated"


# ─── InMemoryVectorStore — delete ─────────────────────────────────────────────

def test_delete_removes_all_chunks_for_doc():
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("c1", "doc-a", [1.0, 0.0]),
        _chunk("c2", "doc-a", [0.9, 0.1]),
        _chunk("c3", "doc-b", [1.0, 0.0]),
    ])
    store.delete("doc-a")
    results = store.search([1.0, 0.0], top_k=10)
    assert not any(r.doc_id == "doc-a" for r in results)
    assert any(r.doc_id == "doc-b" for r in results)


def test_delete_nonexistent_doc_does_not_raise():
    store = InMemoryVectorStore()
    store.upsert([_chunk("c1", "doc1", [1.0, 0.0])])
    store.delete("nonexistent")  # must not raise
    assert store.search([1.0, 0.0], top_k=5)


# ─── InMemoryVectorStore — filter by doc_id ───────────────────────────────────

def test_search_filter_by_doc_id_excludes_others():
    store = InMemoryVectorStore()
    store.upsert([
        _chunk("c1", "doc-a", [1.0, 0.0]),
        _chunk("c2", "doc-b", [1.0, 0.0]),
    ])
    results = store.search([1.0, 0.0], top_k=10, filters={"doc_id": "doc-a"})
    assert all(r.doc_id == "doc-a" for r in results)
    assert len(results) == 1


def test_search_no_filter_returns_all_docs():
    store = InMemoryVectorStore()
    store.upsert([_chunk("c1", "doc-a", [1.0, 0.0]), _chunk("c2", "doc-b", [1.0, 0.0])])
    results = store.search([1.0, 0.0], top_k=10)
    doc_ids = {r.doc_id for r in results}
    assert "doc-a" in doc_ids
    assert "doc-b" in doc_ids


# ─── InMemoryMetadataStore — basic ────────────────────────────────────────────

def test_upsert_and_get_document():
    store = InMemoryMetadataStore()
    store.upsert(_doc("doc1"))
    result = store.get_document("doc1")
    assert result is not None and result.id == "doc1"


def test_get_document_returns_none_for_unknown():
    assert InMemoryMetadataStore().get_document("ghost") is None


def test_upsert_replaces_existing_doc():
    store = InMemoryMetadataStore()
    store.upsert(_doc("doc1", status="pending"))
    store.upsert(_doc("doc1", status="indexed"))
    assert store.get_document("doc1").status == "indexed"


def test_update_status_changes_existing_doc():
    store = InMemoryMetadataStore()
    store.upsert(_doc("doc1", status="pending"))
    store.update_status("doc1", "indexed")
    assert store.get_document("doc1").status == "indexed"


def test_update_status_creates_stub_for_unknown_doc():
    store = InMemoryMetadataStore()
    store.update_status("new-doc", "indexing")
    doc = store.get_document("new-doc")
    assert doc is not None and doc.status == "indexing"


def test_get_by_file_path_finds_correct_doc():
    store = InMemoryMetadataStore()
    store.upsert(_doc("doc1", file_path="s3://bucket/a.pdf"))
    store.upsert(_doc("doc2", file_path="s3://bucket/b.pdf"))
    result = store.get_by_file_path("s3://bucket/a.pdf")
    assert result is not None and result.id == "doc1"


def test_get_by_file_path_returns_none_when_not_found():
    store = InMemoryMetadataStore()
    assert store.get_by_file_path("s3://bucket/missing.pdf") is None


def test_upsert_chunks_does_not_raise():
    from models.ingest_job import ChunkResult
    store = InMemoryMetadataStore()
    chunks = [ChunkResult(chunk_id="c1", doc_id="doc1", content="x")]
    store.upsert_chunks(chunks)  # InMemory is a no-op but must not raise


def test_record_job_does_not_raise():
    store = InMemoryMetadataStore()
    store.record_job(doc_id="doc1", status="indexed", chunk_count=5)  # no-op, must not raise
