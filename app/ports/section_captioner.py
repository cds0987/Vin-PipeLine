from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from app.domain.sections.models import SectionRecord


class SectionCaptioner(Protocol):
    """Generate captions for a batch of sections concurrently."""

    @abstractmethod
    async def caption_sections(self, sections: list[SectionRecord]) -> list[SectionRecord]: ...
