"""
Text parser - converts text-like documents to Markdown.

Primary path uses MarkItDown when available. When that dependency is missing,
the parser falls back to lightweight built-in extractors so ingestion can
continue without crashing in lean environments.
"""
from __future__ import annotations

import io
import os
import tempfile
from html.parser import HTMLParser


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._ignored: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style"}:
            self._ignored.append(tag.lower())

    def handle_endtag(self, tag: str) -> None:
        if self._ignored and self._ignored[-1] == tag.lower():
            self._ignored.pop()

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)

    def get_text(self) -> str:
        return "\n".join(self.parts)


def run(file_bytes: bytes, suffix: str) -> str:
    suffix = suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name
    try:
        try:
            return _convert_markitdown(tmp_path).strip()
        except ModuleNotFoundError:
            return _convert_fallback(file_bytes, suffix).strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _convert_markitdown(path: str) -> str:
    from markitdown import MarkItDown

    result = MarkItDown().convert(path)
    return result.text_content or ""


def _convert_fallback(file_bytes: bytes, suffix: str) -> str:
    if suffix in {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".json", ".yaml", ".yml", ".xml", ".csv", ".rtf"}:
        return file_bytes.decode("utf-8", errors="ignore")
    if suffix in {".html", ".htm"}:
        parser = _HTMLTextExtractor()
        parser.feed(file_bytes.decode("utf-8", errors="ignore"))
        return parser.get_text()
    if suffix == ".docx":
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages if (page.extract_text() or "").strip())
    return file_bytes.decode("utf-8", errors="ignore")
