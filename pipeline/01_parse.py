from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from models.ingest_job import IngestJob
from utils.ai_provider import AIProvider
from utils.storage import read_binary


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if stripped:
            self.parts.append(stripped)

    def get_text(self) -> str:
        return "\n".join(self.parts)


def _parse_pdf(file_bytes: bytes) -> str:
    import io
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(file_bytes))
    return "\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()


def _parse_docx(file_bytes: bytes) -> str:
    import io
    from docx import Document as DocxDocument

    document = DocxDocument(io.BytesIO(file_bytes))
    return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()).strip()


def _parse_text(file_bytes: bytes) -> str:
    return file_bytes.decode("utf-8", errors="ignore").strip()


def _parse_html(file_bytes: bytes) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(file_bytes.decode("utf-8", errors="ignore"))
    return parser.get_text()


def _parse_image(file_bytes: bytes, ai_provider: AIProvider) -> str:
    return ai_provider.ocr(file_bytes).strip()


def run(job: IngestJob, ai_provider: AIProvider) -> str:
    file_bytes = read_binary(job.file_uri)
    suffix = Path(job.file_uri).suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(file_bytes)
    if suffix == ".docx":
        return _parse_docx(file_bytes)
    if suffix in {".txt", ".md"}:
        return _parse_text(file_bytes)
    if suffix in {".html", ".htm"}:
        return _parse_html(file_bytes)
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}:
        return _parse_image(file_bytes, ai_provider)
    return _parse_text(file_bytes)
