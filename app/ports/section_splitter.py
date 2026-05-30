from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from app.domain.documents.models import IngestJob
from app.domain.markdown.models import MarkdownDocument
from app.domain.sections.models import SectionRecord


class SectionSplitter(Protocol):
    """Split a MarkdownDocument into a list of SectionRecords."""

    @abstractmethod
    def split(self, document: MarkdownDocument, job: IngestJob) -> list[SectionRecord]: ...
