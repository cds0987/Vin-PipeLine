from __future__ import annotations

import uuid as _uuid_module

from app.domain.documents.models import SectionRecord
from config import settings


class QdrantStore:
    def __init__(self) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

        qdrant_url = settings.QDRANT_URL or None
        qdrant_api_key = settings.QDRANT_API_KEY or None
        if qdrant_url:
            self._client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        else:
            self._client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

        self._collection = settings.QDRANT_COLLECTION
        existing = {c.name for c in self._client.get_collections().collections}
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=settings.EMBEDDING_DIM, distance=Distance.COSINE),
            )
        else:
            info = self._client.get_collection(self._collection)
            actual_size = getattr(getattr(info.config.params, "vectors", None), "size", None)
            if actual_size is not None and actual_size != settings.EMBEDDING_DIM:
                raise ValueError(
                    f"Qdrant collection '{self._collection}' dimension mismatch: "
                    f"expected {settings.EMBEDDING_DIM}, got {actual_size}"
                )
        self._client.create_payload_index(
            collection_name=self._collection,
            field_name="doc_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    def _point_id(self, section_id: str) -> str:
        return str(_uuid_module.uuid5(_uuid_module.NAMESPACE_DNS, section_id))

    def upsert(self, sections: list[SectionRecord]) -> None:
        from qdrant_client.models import PointStruct

        if not sections:
            return
        for section in sections:
            if len(section.embedding) != settings.EMBEDDING_DIM:
                raise ValueError(
                    f"Embedding dimension mismatch for section_id={section.section_id}: "
                    f"expected {settings.EMBEDDING_DIM}, got {len(section.embedding)}"
                )
        points = [
            PointStruct(
                id=self._point_id(section.section_id),
                vector=section.embedding,
                payload={
                    "section_id": section.section_id,
                    "doc_id": section.doc_id,
                    "section_content": section.section_content,
                    "caption": section.caption,
                    "heading": section.heading,
                    "heading_path": section.heading_path,
                    "section_order": section.section_order,
                    "page_start": section.page_start,
                    "page_end": section.page_end,
                    "source_s3_uri": section.source_s3_uri,
                    "markdown_s3_uri": section.markdown_s3_uri,
                    **section.metadata,
                },
            )
            for section in sections
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[SectionRecord]:
        query_filter = None
        if filters and filters.get("doc_id"):
            from qdrant_client.models import FieldCondition, Filter, MatchValue

            query_filter = Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=filters["doc_id"]))]
            )
        response = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )
        results: list[SectionRecord] = []
        for hit in response.points:
            payload = dict(hit.payload or {})
            # Support both new schema (section_id) and legacy schema (chunk_id)
            section_id = payload.pop("section_id", None) or payload.pop("chunk_id", "")
            doc_id = payload.pop("doc_id", "")
            section_content = payload.pop("section_content", None) or payload.pop("content", "")
            caption = payload.pop("caption", "")
            heading = payload.pop("heading", "")
            heading_path = payload.pop("heading_path", []) or []
            section_order = payload.pop("section_order", 0)
            page_start = payload.pop("page_start", None)
            page_end = payload.pop("page_end", None)
            payload.pop("section", None)
            source_s3_uri = payload.get("source_s3_uri") or payload.get("s3_uri")
            markdown_s3_uri = payload.get("markdown_s3_uri")
            payload["score"] = hit.score
            results.append(SectionRecord(
                section_id=section_id,
                doc_id=doc_id,
                section_content=section_content,
                caption=caption,
                embedding=[],
                heading=heading,
                heading_path=heading_path,
                section_order=section_order,
                page_start=page_start,
                page_end=page_end,
                source_s3_uri=source_s3_uri,
                markdown_s3_uri=markdown_s3_uri,
                metadata=payload,
            ))
        return results

    def delete(self, doc_id: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        self._client.delete(
            collection_name=self._collection,
            points_selector=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )
