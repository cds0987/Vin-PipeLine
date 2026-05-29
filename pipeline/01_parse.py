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


def _parse_pdf(file_bytes: bytes, ai_provider: AIProvider) -> list[tuple[int, str]]:
    import io
    from pypdf import PdfReader

    fitz = None
    rendered_document = None

    def _ocr_page_image_bytes(image_bytes: bytes) -> str:
        try:
            return ai_provider.ocr(image_bytes).strip()
        except Exception:
            return ""

    def _render_pdf_page_as_png(page_index: int) -> bytes | None:
        try:
            if rendered_document is None or fitz is None:
                return None
            pixmap = rendered_document.load_page(page_index).get_pixmap(
                matrix=fitz.Matrix(2, 2),
                alpha=False,
            )
            return pixmap.tobytes("png")
        except Exception:
            return None

    def _ocr_page_images(page) -> str:
        parts: list[str] = []
        for img_obj in getattr(page, "images", []):
            ocr_text = _ocr_page_image_bytes(img_obj.data)
            if ocr_text:
                parts.append(ocr_text)
        return "\n".join(parts).strip()

    try:
        import fitz as fitz_module
        fitz = fitz_module
        rendered_document = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        rendered_document = None

    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        pages: list[tuple[int, str]] = []
        for page_num, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                rendered_page = _render_pdf_page_as_png(page_num - 1)
                if rendered_page:
                    text = _ocr_page_image_bytes(rendered_page)
                if not text:
                    text = _ocr_page_images(page)
            if text:
                pages.append((page_num, text))
        return pages
    finally:
        if rendered_document is not None:
            rendered_document.close()


def _parse_docx(file_bytes: bytes) -> list[tuple[int, str]]:
    import io
    from docx import Document as DocxDocument

    document = DocxDocument(io.BytesIO(file_bytes))
    text = "\n".join(
        paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()
    ).strip()
    return [(1, text)] if text else []


def _parse_text(file_bytes: bytes) -> list[tuple[int, str]]:
    text = file_bytes.decode("utf-8", errors="ignore").strip()
    return [(1, text)] if text else []


def _parse_html(file_bytes: bytes) -> list[tuple[int, str]]:
    parser = _HTMLTextExtractor()
    parser.feed(file_bytes.decode("utf-8", errors="ignore"))
    text = parser.get_text()
    return [(1, text)] if text else []


def _parse_image(file_bytes: bytes, ai_provider: AIProvider) -> list[tuple[int, str]]:
    text = ai_provider.ocr(file_bytes).strip()
    return [(1, text)] if text else []


def run(job: IngestJob, ai_provider: AIProvider) -> list[tuple[int, str]]:
    """Parse file into (page_number, text) tuples."""
    file_bytes = read_binary(job.file_uri)
    suffix = Path(job.file_uri).suffix.lower()
    if suffix == ".pdf":
        return _parse_pdf(file_bytes, ai_provider)
    if suffix == ".docx":
        return _parse_docx(file_bytes)
    if suffix in {".txt", ".md"}:
        return _parse_text(file_bytes)
    if suffix in {".html", ".htm"}:
        return _parse_html(file_bytes)
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}:
        return _parse_image(file_bytes, ai_provider)
    return _parse_text(file_bytes)
