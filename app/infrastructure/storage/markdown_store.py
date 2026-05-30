from __future__ import annotations

from app.domain.documents.models import MarkdownDocument
from app.ports.storage import MarkdownStore
from utils.storage import read_text, write_markdown


class ArtifactMarkdownStore(MarkdownStore):
    def save(self, document: MarkdownDocument) -> MarkdownDocument:
        return write_markdown(document)

    def read(self, markdown_uri: str) -> str:
        return read_text(markdown_uri)
