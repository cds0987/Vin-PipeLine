from __future__ import annotations

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


def test_process_event_returns_none_for_invalid_schema(monkeypatch):
    monkeypatch.setattr("utils.validator.notify", lambda *a, **kw: None)
    monkeypatch.setattr("utils.validator.write_dlq_file", lambda *a, **kw: None)

    result = process_event({"event": "DocumentUploaded"})

    assert result is None


def test_process_event_retries_on_pipeline_failure(monkeypatch):
    attempts = []

    def failing_pipeline(job, **kwargs):
        attempts.append(1)
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("streaming.kafka_consumer.run_pipeline", failing_pipeline)
    monkeypatch.setattr("streaming.kafka_consumer.notify", lambda *a, **kw: None)
    monkeypatch.setattr("streaming.kafka_consumer.write_dlq_file", lambda *a, **kw: None)
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = process_event(VALID_EVENT, retries=3)

    assert result is None
    assert len(attempts) == 3


def test_process_event_sends_to_dlq_after_max_retries(monkeypatch):
    dlq_calls = []

    monkeypatch.setattr("streaming.kafka_consumer.run_pipeline", lambda job, **kwargs: (_ for _ in ()).throw(RuntimeError("fail")))
    monkeypatch.setattr("streaming.kafka_consumer.notify", lambda topic, payload: dlq_calls.append((topic, payload)))
    monkeypatch.setattr("streaming.kafka_consumer.write_dlq_file", lambda *a, **kw: None)
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = process_event(VALID_EVENT, retries=2)

    assert result is None
    assert len(dlq_calls) == 1
    topic, payload = dlq_calls[0]
    assert "DLQ" in topic
    assert payload["reason"] == "pipeline_error"
    assert payload["attempt"] == 2
    assert payload["raw"] == VALID_EVENT


def test_process_event_succeeds_after_transient_failure(monkeypatch):
    call_count = 0

    def flaky_pipeline(job, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            raise RuntimeError("transient error")
        return {"doc_id": job.doc_id, "status": "indexed", "chunk_count": 3}

    monkeypatch.setattr("streaming.kafka_consumer.run_pipeline", flaky_pipeline)
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = process_event(VALID_EVENT, retries=3)

    assert result is not None
    assert result["status"] == "indexed"
    assert call_count == 2
