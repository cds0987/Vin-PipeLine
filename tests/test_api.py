from __future__ import annotations

from adapters.file_adapter import FileAdapter
from models.ingest_job import PermissionModel
from pipeline.run import run


def test_health_endpoint(api_client):
    response = api_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "vector_store" in body
    assert "ai_provider" in body


def test_retrieve_context_endpoint(api_client, fake_ai_provider, vector_store, metadata_store):
    job = FileAdapter().map("data/sample/policy.txt", doc_id="doc-api")
    job.permission = PermissionModel(visibility="public")
    run(job, ai_provider=fake_ai_provider, vector_store=vector_store, metadata_store=metadata_store)

    response = api_client.post(
        "/retrieve-context",
        json={
            "query": "travel reimbursement",
            "user_id": "user-1",
            "user_roles": [],
            "org_id": None,
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["contexts"]
    assert body["contexts"][0]["source"] == "doc-api"


def test_ingest_endpoint_publishes_event(api_client, monkeypatch):
    published = []

    def fake_notify(topic, payload):
        published.append((topic, payload))

    monkeypatch.setattr("api.main.notify", fake_notify)

    response = api_client.post(
        "/ingest",
        json={
            "doc_id": "doc-api-ingest",
            "file_uri": "s3://bucket/policy.pdf",
            "uploaded_by": "user-1",
            "org_id": "org-1",
            "metadata": {"file_name": "policy.pdf", "language": "vi"},
            "permission": {"visibility": "private", "owner_id": "user-1", "org_id": "org-1"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {"doc_id": "doc-api-ingest", "status": "queued"}
    assert len(published) == 1
    assert published[0][0] == "DocumentUploaded"
