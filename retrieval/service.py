from __future__ import annotations

from collections import OrderedDict

from config import settings
from utils.ai_provider import AIProvider, build_ai_provider
from utils.stores import VectorStore, build_vector_store


class RetrievalService:
    def __init__(
        self,
        ai_provider: AIProvider | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self._ai_provider = ai_provider or build_ai_provider()[0]
        self._vector_store = vector_store or build_vector_store()[0]
        self._query_cache: OrderedDict[str, list[float]] = OrderedDict()

    def _embed_query(self, query: str) -> list[float]:
        cached = self._query_cache.get(query)
        if cached is not None:
            self._query_cache.move_to_end(query)
            return cached

        query_vector = self._ai_provider.embed([query])[0]
        self._query_cache[query] = query_vector
        if len(self._query_cache) > settings.SEARCH_QUERY_CACHE_SIZE:
            self._query_cache.popitem(last=False)
        return query_vector

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        query_vector = self._embed_query(query)
        threshold = settings.SEARCH_SCORE_THRESHOLD
        chunks = self._vector_store.search(query_vector, top_k=top_k)
        return [
            {
                "chunk_id": chunk.chunk_id,
                "content": chunk.content,
                "score": chunk.metadata.get("score"),
                "s3_uri": chunk.metadata.get("s3_uri"),
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": chunk.section,
                "doc_id": chunk.doc_id,
            }
            for chunk in chunks
            if threshold == 0.0 or (chunk.metadata.get("score") or 0.0) >= threshold
        ]
