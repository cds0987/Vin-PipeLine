from __future__ import annotations

import re

from app.domain.documents.models import IngestJob, MarkdownDocument, SectionRecord
from app.ports.sectioning import SectionSplitter
from config import settings

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


class HeadingSectionSplitter(SectionSplitter):
    def split(self, document: MarkdownDocument, job: IngestJob) -> list[SectionRecord]:
        markdown_text = document.markdown_content.strip()
        if not markdown_text:
            return []
        sections = self._split_markdown(markdown_text)
        if not sections:
            sections = self._fallback_sections(markdown_text)
        return [
            SectionRecord(
                section_id=f"{job.doc_id}_section_{index:04d}",
                doc_id=job.doc_id,
                section_content=section_content,
                heading=heading_path[-1] if heading_path else "",
                heading_path=heading_path,
                section_order=index,
                markdown_s3_uri=document.markdown_s3_uri,
                source_s3_uri=job.file_uri,
                metadata={
                    "document_type": job.document_type,
                    "language": job.language,
                    "heading_path": heading_path,
                },
            )
            for index, (heading_path, section_content) in enumerate(sections)
        ]

    def _split_markdown(self, markdown_text: str) -> list[tuple[list[str], str]]:
        sections: list[tuple[list[str], str]] = []
        current_path: list[str] = []
        current_lines: list[str] = []

        def flush() -> None:
            content = "\n".join(current_lines).strip()
            if content:
                sections.append((current_path.copy(), content))

        for line in markdown_text.splitlines():
            heading_match = _HEADING_RE.match(line.strip())
            if heading_match:
                flush()
                level = len(heading_match.group(1))
                heading = heading_match.group(2).strip()
                current_path[:] = current_path[: level - 1] + [heading]
                current_lines[:] = [line]
                continue
            current_lines.append(line)

        flush()
        return sections

    def _fallback_sections(self, markdown_text: str) -> list[tuple[list[str], str]]:
        paragraphs = [part.strip() for part in markdown_text.split("\n\n") if part.strip()]
        if not paragraphs:
            return []
        sections: list[tuple[list[str], str]] = []
        batch: list[str] = []
        for paragraph in paragraphs:
            batch.append(paragraph)
            joined = "\n\n".join(batch)
            if (
                len(joined) >= settings.SECTION_FALLBACK_MAX_CHARS
                or len(batch) >= settings.SECTION_FALLBACK_PARAGRAPHS
            ):
                sections.append((["Untitled"], joined))
                batch = []
        if batch:
            sections.append((["Untitled"], "\n\n".join(batch)))
        return sections
