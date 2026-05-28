from __future__ import annotations

from models.ingest_job import ChunkResult, IngestJob
from config import settings


def _tokenize(text: str) -> list[str]:
    return text.split()


def run(text: str, job: IngestJob) -> list[ChunkResult]:
    tokens = _tokenize(text)
    if not tokens:
        return []
    chunk_size = settings.CHUNK_SIZE
    overlap = settings.CHUNK_OVERLAP
    step = max(1, chunk_size - overlap)

    chunks: list[ChunkResult] = []
    for index, start in enumerate(range(0, len(tokens), step)):
        chunk_tokens = tokens[start : start + chunk_size]
        if not chunk_tokens:
            continue
        content = " ".join(chunk_tokens).strip()
        chunks.append(
            ChunkResult(
                chunk_id=f"{job.doc_id}_chunk_{index:04d}",
                doc_id=job.doc_id,
                content=content,
                metadata={
                    "chunk_index": index,
                    "chunk_strategy": "sliding_window",
                    "language": job.language,
                    "document_type": job.document_type,
                    "token_start": start,
                    "token_end": start + len(chunk_tokens),
                },
            )
        )
    return chunks
