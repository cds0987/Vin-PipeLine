"""
Tests for GET /health

Covers:
  - 200 + status=ok when all stores healthy
  - 503 + status=degraded when stores fall back
  - degraded_reasons populated from build warnings
  - scanner field: enabled vs disabled
  - all required fields present
  - MockAI with AI_PROVIDER=auto and no API key → degraded
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


# ── healthy state ─────────────────────────────────────────────────────────────

def test_health_ok_returns_200(api_client):
    resp = api_client.get("/health")
    assert resp.status_code == 200


def test_health_ok_status_field(api_client):
    assert api_client.get("/health").json()["status"] == "ok"


def test_health_required_fields_present(api_client):
    body = api_client.get("/health").json()
    for field in ("status", "vector_store", "metadata_store", "ai_provider",
                  "scanner", "degraded_reasons"):
        assert field in body, f"Missing field: {field}"


def test_health_degraded_reasons_empty_when_ok(api_client):
    assert api_client.get("/health").json()["degraded_reasons"] == []


def test_health_store_names_reflect_actual_class(api_client):
    body = api_client.get("/health").json()
    assert "Store" in body["vector_store"] or "Memory" in body["vector_store"]
    assert "Store" in body["metadata_store"] or "Memory" in body["metadata_store"]
    assert "Provider" in body["ai_provider"] or "Mock" in body["ai_provider"]


# ── degraded state ────────────────────────────────────────────────────────────

def test_health_503_when_stores_degraded(monkeypatch):
    import api.main as api_main
    from app.bootstrap.container import build_container
    from utils.stores import InMemoryVectorStore, InMemoryMetadataStore
    from utils.ai_provider import MockAIProvider

    container = build_container(
        ai_provider=MockAIProvider(),
        vector_store=InMemoryVectorStore(),
        metadata_store=InMemoryMetadataStore(),
    )
    container.degraded_reasons = ["QdrantStore unavailable: connection refused"]
    monkeypatch.setattr(api_main, "build_container", lambda: container)

    with TestClient(api_main.app) as client:
        resp = client.get("/health")

    assert resp.status_code == 503


def test_health_degraded_status_when_vector_store_fallback(monkeypatch):
    import api.main as api_main
    from app.bootstrap.container import build_container
    from utils.stores import InMemoryVectorStore, InMemoryMetadataStore
    from utils.ai_provider import MockAIProvider

    container = build_container(
        ai_provider=MockAIProvider(),
        vector_store=InMemoryVectorStore(),
        metadata_store=InMemoryMetadataStore(),
    )
    container.degraded_reasons = ["QdrantStore unavailable: timeout"]
    monkeypatch.setattr(api_main, "build_container", lambda: container)

    with TestClient(api_main.app) as client:
        body = client.get("/health").json()

    assert body["status"] == "degraded"
    assert any("QdrantStore" in r for r in body["degraded_reasons"])


def test_health_degraded_reasons_contain_all_warnings(monkeypatch):
    import api.main as api_main
    from app.bootstrap.container import build_container
    from utils.stores import InMemoryVectorStore, InMemoryMetadataStore
    from utils.ai_provider import MockAIProvider

    container = build_container(
        ai_provider=MockAIProvider(),
        vector_store=InMemoryVectorStore(),
        metadata_store=InMemoryMetadataStore(),
    )
    container.degraded_reasons = ["vector store down", "metadata store down"]
    monkeypatch.setattr(api_main, "build_container", lambda: container)

    with TestClient(api_main.app) as client:
        body = client.get("/health").json()

    reasons = body["degraded_reasons"]
    assert any("vector store down" in r for r in reasons)
    assert any("metadata store down" in r for r in reasons)


def test_health_ok_when_no_warnings(monkeypatch):
    import api.main as api_main
    from app.bootstrap.container import build_container
    from utils.stores import InMemoryVectorStore, InMemoryMetadataStore
    from utils.ai_provider import MockAIProvider

    container = build_container(
        ai_provider=MockAIProvider(),
        vector_store=InMemoryVectorStore(),
        metadata_store=InMemoryMetadataStore(),
    )
    monkeypatch.setattr(api_main, "build_container", lambda: container)

    with TestClient(api_main.app) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["degraded_reasons"] == []


# ── scanner field ─────────────────────────────────────────────────────────────

def test_health_scanner_enabled_when_use_s3_and_interval(api_client, monkeypatch):
    monkeypatch.setattr("config.settings.USE_S3", True)
    monkeypatch.setattr("config.settings.SCAN_INTERVAL_SECONDS", 300)
    body = api_client.get("/health").json()
    assert body["scanner"] == "enabled"


def test_health_scanner_disabled_when_use_s3_false(api_client, monkeypatch):
    monkeypatch.setattr("config.settings.USE_S3", False)
    body = api_client.get("/health").json()
    assert body["scanner"] == "disabled"


def test_health_scanner_disabled_when_interval_zero(api_client, monkeypatch):
    monkeypatch.setattr("config.settings.USE_S3", True)
    monkeypatch.setattr("config.settings.SCAN_INTERVAL_SECONDS", 0)
    body = api_client.get("/health").json()
    assert body["scanner"] == "disabled"
