from __future__ import annotations

from app.application.search.search_sections import SearchSections
from app.infrastructure.vector.section_index import VectorStoreSectionIndex
from utils.ai_provider import AIProvider, build_ai_provider
from utils.stores import VectorStore, build_vector_store


class RetrievalService:
    def __init__(
        self,
        ai_provider: AIProvider | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        resolved_ai = ai_provider or build_ai_provider()[0]
        resolved_vector = vector_store or build_vector_store()[0]
        self._search = SearchSections(resolved_ai, VectorStoreSectionIndex(resolved_vector))

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        return [
            {
                "section_id": result.section_id,
                "document_id": result.document_id,
                "document_name": result.document_name,
                "caption": result.caption,
                "section_content": result.section_content,
                "markdown_s3_uri": result.markdown_s3_uri,
                "source_s3_uri": result.source_s3_uri,
                "score": result.score,
                "heading_path": result.heading_path,
            }
            for result in self._search.search(query, top_k=top_k)
        ]
