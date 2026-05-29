from __future__ import annotations

import base64
import hashlib
import time
from typing import Any, Protocol

from config import settings

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class AIProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...

    def ocr(self, image_bytes: bytes) -> str:
        ...


class OpenAIProvider:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        embed_model: str | None = None,
        vision_model: str | None = None,
    ) -> None:
        from openai import OpenAI

        resolved_base_url = _normalize_optional_value(base_url) or _normalize_optional_value(settings.AI_BASE_URL)
        resolved_api_key = _normalize_optional_value(api_key) or _normalize_optional_value(settings.AI_API_KEY)
        if not resolved_api_key:
            raise ValueError("AI_API_KEY is required when using OpenAIProvider.")

        self._client: Any = OpenAI(
            base_url=resolved_base_url or OPENAI_DEFAULT_BASE_URL,
            api_key=resolved_api_key,
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
        )
        self._embed_model = embed_model or settings.EMBED_MODEL
        self._vision_model = vision_model or settings.VISION_MODEL

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        attempts = max(1, settings.EMBED_MAX_RETRIES)
        for attempt in range(1, attempts + 1):
            try:
                response = self._client.embeddings.create(model=self._embed_model, input=texts)
                return [item.embedding for item in response.data]
            except Exception:
                if attempt == attempts:
                    raise
                time.sleep(settings.EMBED_RETRY_BACKOFF_SECONDS * attempt)
        return []

    def ocr(self, image_bytes: bytes) -> str:
        attempts = max(1, settings.OCR_MAX_RETRIES)
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        for attempt in range(1, attempts + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._vision_model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{b64_image}"},
                                },
                                {"type": "text", "text": "Extract all text from this image."},
                            ],
                        }
                    ],
                )
                return response.choices[0].message.content or ""
            except Exception:
                if attempt == attempts:
                    raise
                time.sleep(settings.OCR_RETRY_BACKOFF_SECONDS * attempt)
        return ""


class MockAIProvider:
    """Deterministic mock provider for local dev/test before real API credentials are ready."""

    def __init__(self, dimension: int | None = None) -> None:
        self._dimension = dimension or min(settings.EMBEDDING_DIM, 32)

    def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            vector = []
            for index in range(self._dimension):
                byte = digest[index % len(digest)]
                vector.append((byte / 255.0) * 2 - 1)
            embeddings.append(vector)
        return embeddings

    def ocr(self, image_bytes: bytes) -> str:
        return "[mock-ocr] OCR is disabled in mock mode."


def _normalize_optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() in {"none", "null"}:
        return None
    return normalized


def build_ai_provider() -> tuple[AIProvider, str | None]:
    provider_name = (settings.AI_PROVIDER or "auto").lower()
    base_url = _normalize_optional_value(settings.AI_BASE_URL)
    api_key = _normalize_optional_value(settings.AI_API_KEY)

    if provider_name == "mock":
        return MockAIProvider(), None
    if provider_name == "openai":
        return OpenAIProvider(base_url=base_url, api_key=api_key), None
    if provider_name == "auto":
        if api_key:
            return OpenAIProvider(base_url=base_url, api_key=api_key), None
        if not settings.ALLOW_MOCK_AI_FALLBACK:
            raise ValueError("AI_PROVIDER=auto requires AI_API_KEY when ALLOW_MOCK_AI_FALLBACK is false.")
        warning = "AI provider fell back to MockAIProvider because AI_API_KEY is missing."
        return MockAIProvider(), warning
    raise ValueError(
        f"Unsupported AI_PROVIDER='{settings.AI_PROVIDER}'. Expected 'auto', 'mock', or 'openai'."
    )
