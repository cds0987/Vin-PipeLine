# Re-exports for backward compatibility.
# Canonical locations: document_reader.py, markdown_store.py
from app.ports.document_reader import DocumentReader as BinaryReader
from app.ports.markdown_store import MarkdownStore

__all__ = ["BinaryReader", "MarkdownStore"]
