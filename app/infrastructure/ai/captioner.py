from __future__ import annotations

import asyncio

from app.domain.documents.models import SectionRecord
from app.ports.sectioning import SectionCaptioner
from config import settings
from utils.ai_provider import AIProvider


class AISectionCaptioner(SectionCaptioner):
    def __init__(self, ai_provider: AIProvider) -> None:
        self._ai_provider = ai_provider
        self._semaphore = asyncio.Semaphore(settings.CAPTION_MAX_CONCURRENCY)

    async def caption_sections(self, sections: list[SectionRecord]) -> list[SectionRecord]:
        pending = [s for s in sections if not s.caption.strip()]
        if not pending:
            return sections

        captions = await asyncio.gather(*[
            self._caption_one(section.section_content)
            for section in pending
        ])

        if len(captions) != len(pending):
            raise ValueError(
                f"Caption response size mismatch: expected {len(pending)}, got {len(captions)}"
            )

        for section, caption in zip(pending, captions):
            section.caption = (caption or section.section_content[:settings.CAPTION_MAX_CHARS]).strip()
            section.metadata["caption_model"] = settings.CAPTION_MODEL

        return sections

    async def _caption_one(self, text: str) -> str:
        async with self._semaphore:
            caption_fn = getattr(self._ai_provider, "caption", None)
            if callable(caption_fn):
                result = await asyncio.to_thread(caption_fn, [text])
                return result[0] if result else ""
            return text[:settings.CAPTION_MAX_CHARS].strip()
