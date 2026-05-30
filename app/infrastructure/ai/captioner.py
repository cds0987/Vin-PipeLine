from __future__ import annotations

from app.domain.documents.models import SectionRecord
from app.ports.sectioning import SectionCaptioner
from config import settings
from utils.ai_provider import AIProvider


class AISectionCaptioner(SectionCaptioner):
    def __init__(self, ai_provider: AIProvider) -> None:
        self._ai_provider = ai_provider

    def caption_sections(self, sections: list[SectionRecord]) -> list[SectionRecord]:
        pending = [section for section in sections if not section.caption.strip()]
        if not pending:
            return sections

        caption_fn = getattr(self._ai_provider, "caption", None)
        if callable(caption_fn):
            generated = caption_fn([section.section_content for section in pending])
        else:
            generated = [section.section_content[: settings.CAPTION_MAX_CHARS].strip() for section in pending]

        if len(generated) != len(pending):
            raise ValueError(
                f"Caption response size mismatch: expected {len(pending)}, got {len(generated)}"
            )

        for section, caption in zip(pending, generated):
            section.caption = (caption or section.section_content[: settings.CAPTION_MAX_CHARS]).strip()
            section.metadata["caption_model"] = settings.CAPTION_MODEL
        return sections
