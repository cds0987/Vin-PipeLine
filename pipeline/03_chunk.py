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
    return list(range(len(text.split())))


def _decode(token_ids: list[int]) -> str:
    if _ENCODER is not None:
        return _ENCODER.decode(token_ids)
    return " ".join(str(t) for t in token_ids)


def _build_token_page_map(pages: list[tuple[int, str]]) -> tuple[list[int], list[int]]:
    """
    Tokenise each page separately to build a token→page mapping, then return
    (full_tokens, token_to_page) for the concatenated text.

    Pages are joined with "\n\n" whose separator tokens are attributed to the
    preceding page.  This is an approximation: BPE merges at page boundaries
    may produce a slightly different token sequence than tokenising the whole
    text at once, but the difference is negligible for citation purposes.
    """
    full_tokens: list[int] = []
    token_to_page: list[int] = []
    sep_tokens = _tokenize("\n\n")

    for i, (page_num, text) in enumerate(pages):
        page_tokens = _tokenize(text)
        full_tokens.extend(page_tokens)
        token_to_page.extend([page_num] * len(page_tokens))
        if i < len(pages) - 1:
            full_tokens.extend(sep_tokens)
            token_to_page.extend([page_num] * len(sep_tokens))

    return full_tokens, token_to_page


def run(pages: list[tuple[int, str]], job: IngestJob) -> list[ChunkResult]:
    """Sliding-window BPE chunking with page_start / page_end tracking."""
    if not pages:
        return []

    full_tokens, token_to_page = _build_token_page_map(pages)
    if not full_tokens:
        return []

    chunk_size = settings.CHUNK_SIZE
    overlap = settings.CHUNK_OVERLAP
    step = max(1, chunk_size - overlap)

    chunks: list[ChunkResult] = []
    for index, start in enumerate(range(0, len(full_tokens), step)):
        chunk_tokens = full_tokens[start : start + chunk_size]
        if not chunk_tokens:
            continue
        content = _decode(chunk_tokens).strip()
        if not content:
            continue

        chunk_pages = token_to_page[start : start + len(chunk_tokens)]
        page_start = chunk_pages[0] if chunk_pages else None
        page_end = chunk_pages[-1] if chunk_pages else None

        chunks.append(
            ChunkResult(
                chunk_id=f"{job.doc_id}_chunk_{index:04d}",
                doc_id=job.doc_id,
                content=content,
                page_start=page_start,
                page_end=page_end,
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
