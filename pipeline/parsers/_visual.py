"""
Visual parser — converts image-heavy or mixed-content documents to Markdown.

Two paths:
  1. Standalone images (.png/.jpg/…)
       → direct OCR via AIProvider.ocr()

  2. Mixed documents (.pdf/.docx/.pptx/.xlsx/…)
       → MarkItDown with llm_client (GPT-4o / OpenRouter vision model)
         handles text layer AND embedded images in one pass
       → fallback when no llm_client (mock/test mode): text-only via _text.run()

Removing the old fitz + pptx image-extraction loops — MarkItDown with a
vision-capable llm_client covers the same ground with higher quality and
fewer moving parts.
"""
from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

from config import settings

if TYPE_CHECKING:
    from utils.ai_provider import AIProvider

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"})

# OCR results shorter than this are treated as noise and discarded.
_MIN_OCR_CHARS = 10

# PDF pages with fewer extracted chars than this are treated as image pages.
_SPARSE_PAGE_THRESHOLD = 50

# If MarkItDown extracts fewer chars than this from a PDF, fall back to
# page-level OCR (handles fully scanned / image-only PDFs).
_PDF_LLM_FALLBACK_THRESHOLD = 50

# pymupdf render scale — higher = sharper, better OCR accuracy.
_PDF_RENDER_SCALE = 1.5


def run(file_bytes: bytes, suffix: str, ai_provider: AIProvider) -> str:
    """Convert an image-heavy or mixed-content file to a Markdown string.

    Args:
        file_bytes: raw bytes of the document.
        suffix: file extension with dot, e.g. ``".pdf"``, ``".png"``.
        ai_provider: used for OCR (images) or to supply the LLM client
            (mixed documents).

    Returns:
        Markdown string. Empty string when no content can be extracted.
    """
    suffix = suffix.lower()

    if suffix in _IMAGE_SUFFIXES:
        return _parse_image(file_bytes, ai_provider)

    return _parse_mixed(file_bytes, suffix, ai_provider)


# ── format handlers ───────────────────────────────────────────────────────────


def _parse_image(file_bytes: bytes, ai_provider: AIProvider) -> str:
    """OCR a standalone image file directly."""
    text = ai_provider.ocr(file_bytes).strip()
    return text if len(text) >= _MIN_OCR_CHARS else ""


def _parse_mixed(file_bytes: bytes, suffix: str, ai_provider: AIProvider) -> str:
    """Parse a document that may contain both text and embedded images.

    Primary path: MarkItDown + vision LLM (handles text layer and embedded
    image descriptions in one pass).

    PDF fallback: if MarkItDown returns too little text the PDF is likely
    fully scanned — render each sparse page with pymupdf and OCR it.

    Mock mode (no llm_client): text-only extraction via _text.run().
    """
    llm_client = ai_provider.get_llm_client()
    if not llm_client:
        # No vision LLM available — try text extraction first.
        text = _text_extract(file_bytes, suffix)
        # Image-based PDFs produce no extractable text; fall back to page OCR.
        if suffix == ".pdf" and len(text.strip()) < _PDF_LLM_FALLBACK_THRESHOLD:
            ocr_parts = _ocr_sparse_pdf_pages(file_bytes, ai_provider)
            if ocr_parts:
                return _join(text, ocr_parts)
        return text

    markdown = _convert_with_llm(file_bytes, suffix, llm_client)

    # Scanned / image-only PDF: MarkItDown finds no text layer.
    if suffix == ".pdf" and len(markdown.strip()) < _PDF_LLM_FALLBACK_THRESHOLD:
        ocr_parts = _ocr_sparse_pdf_pages(file_bytes, ai_provider)
        if ocr_parts:
            return _join(markdown, ocr_parts)

    return markdown


# ── helpers ───────────────────────────────────────────────────────────────────


def _convert_with_llm(file_bytes: bytes, suffix: str, llm_client) -> str:
    """Run MarkItDown with a vision-capable LLM client."""
    try:
        from markitdown import MarkItDown
    except ModuleNotFoundError:
        return _text_extract(file_bytes, suffix)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(file_bytes)
        tmp_path = f.name
    try:
        md = MarkItDown(
            enable_plugins=True,
            llm_client=llm_client,
            llm_model=settings.VISION_MODEL,
        )
        result = md.convert(tmp_path)
        return (result.text_content or "").strip()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _ocr_sparse_pdf_pages(file_bytes: bytes, ai_provider: AIProvider) -> list[str]:
    """Render and OCR PDF pages that have no extractable text layer."""
    try:
        import fitz
    except ImportError:
        return []

    results: list[str] = []
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return []
    try:
        for page_index in range(len(doc)):
            page = doc.load_page(page_index)
            if len(page.get_text().strip()) >= _SPARSE_PAGE_THRESHOLD:
                continue
            try:
                matrix = fitz.Matrix(_PDF_RENDER_SCALE, _PDF_RENDER_SCALE)
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                image_bytes = pix.tobytes("png")
            except Exception:
                continue
            ocr_text = ai_provider.ocr(image_bytes).strip()
            if len(ocr_text) >= _MIN_OCR_CHARS:
                results.append(f"<!-- page {page_index + 1} -->\n{ocr_text}")
    finally:
        doc.close()
    return results


def _join(text_markdown: str, ocr_parts: list[str]) -> str:
    parts = [text_markdown] + ocr_parts
    return "\n\n".join(p for p in parts if p.strip())


def _text_extract(file_bytes: bytes, suffix: str) -> str:
    """Text-only fallback — no LLM, no OCR."""
    from pipeline.parsers._text import run as text_run
    return text_run(file_bytes, suffix)
