from __future__ import annotations

from adapters.kafka_adapter import KafkaAdapter


def test_kafka_adapter_returns_none_for_invalid_event(monkeypatch):
    dlq_calls = []

    monkeypatch.setattr("utils.validator.notify", lambda topic, payload: dlq_calls.append((topic, payload)))
    monkeypatch.setattr("utils.validator.write_dlq_file", lambda file_name, payload: file_name)

    job = KafkaAdapter().map({"event": "DocumentUploaded"})

    assert job is None
    assert dlq_calls
