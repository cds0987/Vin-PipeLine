from __future__ import annotations

from app.domain.documents.models import SectionRecord
from app.ports.vector_index import SectionIndex
from utils.stores import VectorStore


class VectorStoreSectionIndex(SectionIndex):
    def __init__(self, vector_store: VectorStore) -> None:
        self._vector_store = vector_store

    def upsert_sections(self, sections: list[SectionRecord]) -> None:
        enriched = [
            section.model_copy(update={
                "metadata": {
                    **section.metadata,
                    "section_id": section.section_id,
                    "section_content": section.section_content,
                    "caption": section.caption,
                    "heading": section.heading,
                    "heading_path": section.heading_path,
                    "section_order": section.section_order,
                    "s3_uri": section.source_s3_uri,
                    "source_s3_uri": section.source_s3_uri,
                    "markdown_s3_uri": section.markdown_s3_uri,
                },
            })
            for section in sections
        ]
        self._vector_store.upsert(enriched)

    def search_sections(self, vector: list[float], top_k: int) -> list[SectionRecord]:
        results = self._vector_store.search(vector, top_k=top_k)
        return [
            SectionRecord(
                section_id=result.section_id or result.metadata.get("section_id") or result.metadata.get("chunk_id", ""),
                doc_id=result.doc_id,
                section_content=result.section_content or result.metadata.get("content", ""),
                caption=result.caption or result.metadata.get("caption", ""),
                embedding=[],
                heading=result.heading or result.metadata.get("heading", ""),
                heading_path=result.heading_path or result.metadata.get("heading_path") or [],
                section_order=result.section_order or result.metadata.get("section_order", 0),
                markdown_s3_uri=result.markdown_s3_uri or result.metadata.get("markdown_s3_uri"),
                source_s3_uri=result.source_s3_uri or result.metadata.get("source_s3_uri") or result.metadata.get("s3_uri"),
                metadata=result.metadata,
            )
            for result in results
        ]

    def delete_document(self, doc_id: str) -> None:
        self._vector_store.delete(doc_id)
