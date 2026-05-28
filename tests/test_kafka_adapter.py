from __future__ import annotations

from adapters.kafka_adapter import KafkaAdapter


def test_kafka_adapter_maps_valid_event():
    job = KafkaAdapter().map(
        {
            "event": "DocumentUploaded",
            "schema_version": "1.0",
            "doc_id": "doc-1",
            "s3_uri": "s3://bucket/file.pdf",
            "uploaded_by": "user-1",
            "org_id": "org-1",
            "metadata": {"file_name": "file.pdf", "document_type": "policy", "language": "vi"},
            "permission": {"visibility": "private", "owner_id": "user-1", "org_id": "org-1"},
            "timestamp": "2026-05-29T10:00:00Z",
        }
    )

    assert job is not None
    assert job.doc_id == "doc-1"
    assert job.file_uri == "s3://bucket/file.pdf"
    assert job.document_type == "policy"


def test_kafka_adapter_returns_none_for_invalid_event(monkeypatch):
    dlq_calls = []

    monkeypatch.setattr("utils.validator.notify", lambda topic, payload: dlq_calls.append((topic, payload)))
    monkeypatch.setattr("utils.validator.write_dlq_file", lambda file_name, payload: file_name)

    job = KafkaAdapter().map({"event": "DocumentUploaded"})

    assert job is None
    assert dlq_calls
