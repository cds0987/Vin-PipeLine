"""
Tests for OpenAIProvider retry + backoff logic.

embed() and ocr() retry on failure up to EMBED_MAX_RETRIES / OCR_MAX_RETRIES,
sleeping EMBED_RETRY_BACKOFF_SECONDS * attempt between tries.
"""
from __future__ import annotations

import sys
import time
import types

import pytest


# ── helpers: fake OpenAI client ───────────────────────────────────────────────

class _FakeEmbeddingItem:
    def __init__(self, vector): self.embedding = vector


class _FakeEmbeddingResponse:
    def __init__(self, vectors):
        self.data = [_FakeEmbeddingItem(v) for v in vectors]


class _FakeEmbeddingsClient:
    def __init__(self, responses: list):
        self._queue = list(responses)
        self.call_count = 0

    def create(self, model, input):
        self.call_count += 1
        resp = self._queue.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class _FakeChatCompletions:
    def __init__(self, responses: list):
        self._queue = list(responses)
        self.call_count = 0

    def create(self, model, messages):
        self.call_count += 1
        resp = self._queue.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


class _FakeMessage:
    def __init__(self, text): self.content = text


class _FakeChoice:
    def __init__(self, text): self.message = _FakeMessage(text)


class _FakeChatResponse:
    def __init__(self, text): self.choices = [_FakeChoice(text)]


class _FakeOpenAIClient:
    def __init__(self, embed_responses=None, chat_responses=None):
        self.embeddings = _FakeEmbeddingsClient(embed_responses or [])
        self.chat = types.SimpleNamespace(
            completions=_FakeChatCompletions(chat_responses or [])
        )


def _make_provider(monkeypatch, embed_responses=None, chat_responses=None):
    """Construct an OpenAIProvider with injected fake client."""
    fake_client = _FakeOpenAIClient(embed_responses, chat_responses)

    fake_openai_mod = types.ModuleType("openai")
    fake_openai_mod.OpenAI = lambda **kwargs: fake_client
    monkeypatch.setitem(sys.modules, "openai", fake_openai_mod)

    from utils.ai_provider import OpenAIProvider
    provider = OpenAIProvider(api_key="test-key", embed_model="e-model", vision_model="v-model")
    # Expose the fake client for call count assertions
    provider._fake_client = fake_client
    return provider


# ── embed() retry ─────────────────────────────────────────────────────────────

def test_embed_succeeds_first_try(monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MAX_RETRIES", 3)
    monkeypatch.setattr("config.settings.EMBED_RETRY_BACKOFF_SECONDS", 0.0)

    dim = 4
    provider = _make_provider(
        monkeypatch,
        embed_responses=[_FakeEmbeddingResponse([[0.1] * dim])],
    )
    result = provider.embed(["hello"])
    assert result == [[0.1] * dim]
    assert provider._fake_client.embeddings.call_count == 1


def test_embed_retries_on_failure_then_succeeds(monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MAX_RETRIES", 3)
    monkeypatch.setattr("config.settings.EMBED_RETRY_BACKOFF_SECONDS", 0.0)

    dim = 4
    provider = _make_provider(
        monkeypatch,
        embed_responses=[
            RuntimeError("transient error"),
            RuntimeError("transient error"),
            _FakeEmbeddingResponse([[0.5] * dim]),
        ],
    )
    result = provider.embed(["hello"])
    assert result == [[0.5] * dim]
    assert provider._fake_client.embeddings.call_count == 3


def test_embed_raises_after_max_retries_exhausted(monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MAX_RETRIES", 2)
    monkeypatch.setattr("config.settings.EMBED_RETRY_BACKOFF_SECONDS", 0.0)

    provider = _make_provider(
        monkeypatch,
        embed_responses=[
            RuntimeError("fail 1"),
            RuntimeError("fail 2"),
        ],
    )
    with pytest.raises(RuntimeError, match="fail 2"):
        provider.embed(["query"])
    assert provider._fake_client.embeddings.call_count == 2


def test_embed_sleeps_between_retries(monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MAX_RETRIES", 2)
    monkeypatch.setattr("config.settings.EMBED_RETRY_BACKOFF_SECONDS", 0.5)

    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    dim = 2
    provider = _make_provider(
        monkeypatch,
        embed_responses=[
            RuntimeError("fail"),
            _FakeEmbeddingResponse([[0.1] * dim]),
        ],
    )
    provider.embed(["x"])
    # Should have slept once: 0.5 * attempt(1) = 0.5
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(0.5)


def test_embed_backoff_scales_with_attempt(monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MAX_RETRIES", 3)
    monkeypatch.setattr("config.settings.EMBED_RETRY_BACKOFF_SECONDS", 1.0)

    sleep_calls: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

    dim = 2
    provider = _make_provider(
        monkeypatch,
        embed_responses=[
            RuntimeError("fail 1"),
            RuntimeError("fail 2"),
            _FakeEmbeddingResponse([[0.1] * dim]),
        ],
    )
    provider.embed(["x"])
    # Attempt 1 fails → sleep(1.0 * 1)
    # Attempt 2 fails → sleep(1.0 * 2)
    assert sleep_calls == pytest.approx([1.0, 2.0])


def test_embed_empty_input_returns_empty_without_calling_api(monkeypatch):
    monkeypatch.setattr("config.settings.EMBED_MAX_RETRIES", 3)
    monkeypatch.setattr("config.settings.EMBED_RETRY_BACKOFF_SECONDS", 0.0)

    provider = _make_provider(monkeypatch, embed_responses=[])
    result = provider.embed([])
    assert result == []
    assert provider._fake_client.embeddings.call_count == 0


# ── ocr() retry ───────────────────────────────────────────────────────────────

def test_ocr_succeeds_first_try(monkeypatch):
    monkeypatch.setattr("config.settings.OCR_MAX_RETRIES", 2)
    monkeypatch.setattr("config.settings.OCR_RETRY_BACKOFF_SECONDS", 0.0)

    provider = _make_provider(
        monkeypatch,
        chat_responses=[_FakeChatResponse("extracted text")],
    )
    result = provider.ocr(b"image_bytes")
    assert result == "extracted text"
    assert provider._fake_client.chat.completions.call_count == 1


def test_ocr_retries_on_failure_then_succeeds(monkeypatch):
    monkeypatch.setattr("config.settings.OCR_MAX_RETRIES", 3)
    monkeypatch.setattr("config.settings.OCR_RETRY_BACKOFF_SECONDS", 0.0)

    provider = _make_provider(
        monkeypatch,
        chat_responses=[
            RuntimeError("api down"),
            _FakeChatResponse("ocr result"),
        ],
    )
    result = provider.ocr(b"img")
    assert result == "ocr result"
    assert provider._fake_client.chat.completions.call_count == 2


def test_ocr_raises_after_all_retries_fail(monkeypatch):
    monkeypatch.setattr("config.settings.OCR_MAX_RETRIES", 2)
    monkeypatch.setattr("config.settings.OCR_RETRY_BACKOFF_SECONDS", 0.0)

    provider = _make_provider(
        monkeypatch,
        chat_responses=[RuntimeError("fail 1"), RuntimeError("fail 2")],
    )
    with pytest.raises(RuntimeError, match="fail 2"):
        provider.ocr(b"img")


def test_ocr_returns_empty_string_when_message_content_is_none(monkeypatch):
    monkeypatch.setattr("config.settings.OCR_MAX_RETRIES", 1)
    monkeypatch.setattr("config.settings.OCR_RETRY_BACKOFF_SECONDS", 0.0)

    class _NoneContentResponse:
        choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=None))]

    provider = _make_provider(monkeypatch, chat_responses=[_NoneContentResponse()])
    result = provider.ocr(b"img")
    assert result == ""
