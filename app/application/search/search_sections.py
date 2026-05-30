from __future__ import annotations

import logging
import time
from collections import OrderedDict
from threading import Lock

from app.domain.retrieval.models import SectionSearchResult
from app.ports.ai import EmbeddingProvider
from app.ports.vector_index import SectionIndex
from config import settings

log = logging.getLogger(__name__)


class SearchSections:
    def __init__(self, embedding_provider: EmbeddingProvider, section_index: SectionIndex) -> None:
        self._embedding_provider = embedding_provider
        self._section_index = section_index
        self._query_cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_lock = Lock()

    def search(self, query: str, top_k: int = 5, request_id: str | None = None) -> list[SectionSearchResult]:
        log.info(
            "search_received request_id=%s query_length=%d top_k=%d threshold=%s",
            request_id, len(query), top_k, settings.SEARCH_SCORE_THRESHOLD,
        )

        t0 = time.perf_counter()
        query_vector = self._embed_query(query)
        log.info(
            "query_embedded request_id=%s embedding_model=%s duration_ms=%d",
            request_id,
            self._embedding_provider.__class__.__name__,
            round((time.perf_counter() - t0) * 1000),
        )

        threshold = settings.SEARCH_SCORE_THRESHOLD
        fetch_k = top_k * 3 if threshold > 0.0 else top_k

        t0 = time.perf_counter()
        raw_results = self._section_index.search_sections(query_vector, top_k=fetch_k)
        log.info(
            "vector_search_completed request_id=%s candidates=%d threshold=%s duration_ms=%d",
            request_id, len(raw_results), threshold,
            round((time.perf_counter() - t0) * 1000),
        )

        mapped = []
        for section in raw_results:
            score = float(section.metadata.get("score", 0.0))
            if threshold != 0.0 and score < threshold:
                continue
            mapped.append(
                SectionSearchResult(
                    section_id=section.section_id,
                    document_id=section.doc_id,
                    document_name=section.metadata.get("file_name") or section.metadata.get("document_name") or section.doc_id,
                    caption=section.caption,
                    section_content=section.section_content,
                    markdown_s3_uri=section.markdown_s3_uri,
                    source_s3_uri=section.source_s3_uri,
                    score=score,
                    heading_path=section.heading_path,
                )
            )
        results = mapped[:top_k]

        top_section_id = results[0].section_id if results else None
        top_doc_id = results[0].document_id if results else None
        log.info(
            "search_completed request_id=%s result_count=%d top_section_id=%s top_doc_id=%s",
            request_id, len(results), top_section_id, top_doc_id,
        )
        return results

    def _embed_query(self, query: str) -> list[float]:
        with self._cache_lock:
            cached = self._query_cache.get(query)
            if cached is not None:
                self._query_cache.move_to_end(query)
                return cached
        query_vector = self._embedding_provider.embed([query])[0]
        with self._cache_lock:
            self._query_cache[query] = query_vector
            if len(self._query_cache) > settings.SEARCH_QUERY_CACHE_SIZE:
                self._query_cache.popitem(last=False)
        return query_vector
