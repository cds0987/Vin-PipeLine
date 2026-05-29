"""
AI provider tests — covers gaps not in existing suite:
  - _normalize_optional_value (None, empty, "none"/"null" sentinel strings)
  - MockAIProvider: dimension, determinism, value range, empty list
  - build_ai_provider: mock/auto/unknown branch selection
"""
from __future__ import annotations

import pytest

from utils.ai_provider import MockAIProvider, _normalize_optional_value, build_ai_provider


# ─── _normalize_optional_value ────────────────────────────────────────────────

def test_normalize_none_returns_none():
    assert _normalize_optional_value(None) is None


def test_normalize_empty_string_returns_none():
    assert _normalize_optional_value("") is None


def test_normalize_whitespace_only_returns_none():
    assert _normalize_optional_value("   ") is None


@pytest.mark.parametrize("sentinel", ["none", "None", "NONE", "null", "Null", "NULL"])
def test_normalize_sentinel_strings_return_none(sentinel):
    assert _normalize_optional_value(sentinel) is None


def test_normalize_valid_value_strips_and_returns():
    assert _normalize_optional_value("  sk-abc123  ") == "sk-abc123"


def test_normalize_valid_value_unchanged_when_no_whitespace():
    assert _normalize_optional_value("some-api-key") == "some-api-key"


# ─── MockAIProvider.embed ─────────────────────────────────────────────────────

def test_mock_embed_returns_correct_dimension():
    provider = MockAIProvider(dimension=16)
    result = provider.embed(["hello"])
    assert len(result) == 1
    assert len(result[0]) == 16


def test_mock_embed_empty_list_returns_empty():
    assert MockAIProvider(dimension=8).embed([]) == []


def test_mock_embed_multiple_texts_each_get_vector():
    provider = MockAIProvider(dimension=4)
    results = provider.embed(["a", "b", "c"])
    assert len(results) == 3
    assert all(len(v) == 4 for v in results)


def test_mock_embed_is_deterministic():
    provider = MockAIProvider(dimension=8)
    v1 = provider.embed(["same text"])[0]
    v2 = provider.embed(["same text"])[0]
    assert v1 == v2


def test_mock_embed_different_texts_give_different_vectors():
    provider = MockAIProvider(dimension=8)
    assert provider.embed(["alpha"])[0] != provider.embed(["beta"])[0]


def test_mock_embed_values_in_minus_one_to_one_range():
    provider = MockAIProvider(dimension=32)
    for v in provider.embed(["test string"])[0]:
        assert -1.0 <= v <= 1.0


# ─── MockAIProvider.ocr ───────────────────────────────────────────────────────

def test_mock_ocr_returns_non_empty_string():
    result = MockAIProvider().ocr(b"image bytes")
    assert isinstance(result, str)
    assert len(result) > 0


def test_mock_ocr_does_not_raise_on_empty_bytes():
    MockAIProvider().ocr(b"")  # must not raise


# ─── build_ai_provider ────────────────────────────────────────────────────────

def test_build_returns_mock_when_provider_is_mock(monkeypatch):
    monkeypatch.setattr("config.settings.AI_PROVIDER", "mock")
    assert isinstance(build_ai_provider(), MockAIProvider)


def test_build_auto_without_key_returns_mock(monkeypatch):
    monkeypatch.setattr("config.settings.AI_PROVIDER", "auto")
    monkeypatch.setattr("config.settings.AI_API_KEY", None)
    monkeypatch.setattr("config.settings.AI_BASE_URL", None)
    assert isinstance(build_ai_provider(), MockAIProvider)


def test_build_auto_with_whitespace_key_returns_mock(monkeypatch):
    """Key that normalizes to None must fall through to Mock."""
    monkeypatch.setattr("config.settings.AI_PROVIDER", "auto")
    monkeypatch.setattr("config.settings.AI_API_KEY", "   ")
    monkeypatch.setattr("config.settings.AI_BASE_URL", None)
    assert isinstance(build_ai_provider(), MockAIProvider)


def test_build_unknown_provider_raises_value_error(monkeypatch):
    monkeypatch.setattr("config.settings.AI_PROVIDER", "anthropic")
    with pytest.raises(ValueError, match="Unsupported AI_PROVIDER"):
        build_ai_provider()
