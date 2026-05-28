from __future__ import annotations

from dataclasses import dataclass

from models.ingest_job import PermissionModel
from utils.ai_provider import AIProvider, build_ai_provider
from utils.stores import MetadataStore, VectorStore, build_metadata_store, build_vector_store


@dataclass
class RetrievalRequest:
    query: str
    user_id: str
    user_roles: list[str]
    org_id: str | None
    top_k: int = 5


class RetrievalService:
    def __init__(
        self,
        ai_provider: AIProvider | None = None,
        vector_store: VectorStore | None = None,
        metadata_store: MetadataStore | None = None,
    ) -> None:
        self._ai_provider = ai_provider or build_ai_provider()
        self._vector_store = vector_store or build_vector_store()
        self._metadata_store = metadata_store or build_metadata_store()

    def retrieve(self, request: RetrievalRequest) -> list[dict]:
        query_vector = self._ai_provider.embed([request.query])[0]
        candidates = self._vector_store.search(query_vector, top_k=request.top_k * 3, filters={})
        contexts: list[dict] = []
        for chunk in candidates:
            permission = self._metadata_store.get_permission(chunk.doc_id)
            if not self._is_allowed(permission, request):
                continue
            contexts.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "content": chunk.content,
                    "score": chunk.metadata.get("score"),
                    "source": chunk.doc_id,
                    "metadata": chunk.metadata,
                }
            )
            if len(contexts) >= request.top_k:
                break
        return contexts

    @staticmethod
    def _is_allowed(permission: PermissionModel | None, request: RetrievalRequest) -> bool:
        if permission is None:
            return False
        if permission.visibility == "public":
            return True
        if request.user_id and request.user_id == permission.owner_id:
            return True
        if set(request.user_roles).intersection(permission.allowed_roles):
            return True
        if request.user_id in permission.allowed_users:
            return True
        if permission.visibility == "org" and request.org_id and request.org_id == permission.org_id:
            return True
        return False
