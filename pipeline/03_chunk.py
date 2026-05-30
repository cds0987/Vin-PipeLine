from __future__ import annotations

from app.domain.documents.models import MarkdownDocument
from app.infrastructure.sectioning.heading_splitter import HeadingSectionSplitter
from models.ingest_job import ChunkResult, IngestJob


def run(
    pages_or_markdown: list[tuple[int, str]] | MarkdownDocument | str,
    job: IngestJob,
    markdown_s3_uri: str | None = None,
    source_s3_uri: str | None = None,
) -> list[ChunkResult]:
    if isinstance(pages_or_markdown, list):
        markdown_content = "\n\n".join(text for _, text in pages_or_markdown if text.strip())
    elif isinstance(pages_or_markdown, MarkdownDocument):
        markdown_content = pages_or_markdown.markdown_content
        markdown_s3_uri = markdown_s3_uri or pages_or_markdown.markdown_s3_uri
    else:
        markdown_content = pages_or_markdown

    document = MarkdownDocument(
        doc_id=job.doc_id,
        source_uri=source_s3_uri or job.file_uri,
        markdown_content=markdown_content,
        markdown_s3_uri=markdown_s3_uri,
        title=job.file_name,
    )
    return HeadingSectionSplitter().split(document, job)
