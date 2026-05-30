from __future__ import annotations

from app.domain.documents.models import SectionRecord


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._sections: dict[str, SectionRecord] = {}

    def upsert(self, sections: list[SectionRecord]) -> None:
        for section in sections:
            self._sections[section.section_id] = section

    def search(self, vector: list[float], top_k: int, filters: dict | None = None) -> list[SectionRecord]:
        scored = []
        for section in self._sections.values():
            if filters and filters.get("doc_id") and section.doc_id != filters["doc_id"]:
                continue
            score = _cosine_similarity(vector, section.embedding)
            merged = section.model_copy(deep=True)
            merged.metadata["score"] = score
            scored.append(merged)
        scored.sort(key=lambda item: item.metadata.get("score", 0), reverse=True)
        return scored[:top_k]

    def delete(self, doc_id: str) -> None:
        to_remove = [sid for sid, s in self._sections.items() if s.doc_id == doc_id]
        for sid in to_remove:
            del self._sections[sid]
