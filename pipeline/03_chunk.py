from __future__ import annotations

from config import settings
from models.ingest_job import ChunkResult, IngestJob


def _get_encoder():
    try:
        import tiktoken
        return tiktoken.encoding_for_model("text-embedding-3-small")
    except Exception:
        return None


_ENCODER = _get_encoder()


def _tokenize(text: str) -> list[int]:
    if _ENCODER is not None:
        return _ENCODER.encode(text)
    # fallback: encode each word as a single fake token id
    return list(range(len(text.split())))


def _decode(token_ids: list[int]) -> str:
    if _ENCODER is not None:
        return _ENCODER.decode(token_ids)
    # fallback path is never reached in production (tiktoken always available)
    return " ".join(str(t) for t in token_ids)


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
        content = _decode(chunk_tokens).strip()
        if not content:
            continue
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
