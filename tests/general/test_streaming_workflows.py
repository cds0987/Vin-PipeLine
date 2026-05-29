from __future__ import annotations

from adapters.kafka_adapter import KafkaAdapter
from streaming.kafka_consumer import process_event


VALID_EVENT = {
    "event": "DocumentUploaded",
    "schema_version": "1.0",
    "doc_id": "doc-consumer-test",
    "s3_uri": "s3://bucket/file.pdf",
    "uploaded_by": "user-1",
    "org_id": "org-1",
    "metadata": {"file_name": "file.pdf", "language": "vi"},
    "permission": {"visibility": "private", "owner_id": "user-1"},
    "timestamp": "2026-05-29T10:00:00Z",
}


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
            "timestamp": "2026-05-29T10:00:00Z",
        }
    )

    assert job is not None
    assert job.doc_id == "doc-1"
    assert job.file_uri == "s3://bucket/file.pdf"
    assert job.document_type == "policy"


def test_process_event_succeeds_on_first_attempt(monkeypatch):
    monkeypatch.setattr(
        "streaming.kafka_consumer.run_pipeline",
        lambda job, **kwargs: {"doc_id": job.doc_id, "status": "indexed", "chunk_count": 5},
    )

    result = process_event(VALID_EVENT)

    assert result is not None
    assert result["status"] == "indexed"
