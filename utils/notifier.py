from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from config import settings
from models.events import EmbeddingDone, IndexingFailed

log = logging.getLogger(__name__)
_producer = None
_producer_lock = threading.Lock()


def _get_producer():
    global _producer
    if _producer is not None:
        return _producer
    with _producer_lock:
        if _producer is None:
            from kafka import KafkaProducer

            _producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP,
                value_serializer=lambda value: json.dumps(value, default=str).encode("utf-8"),
                retries=3,
            )
    return _producer


def notify(topic: str, payload: dict) -> None:
    message = {
        **payload,
        "event": payload.get("event", topic),
        "schema_version": payload.get("schema_version", "1.0"),
        "emitted_at": datetime.utcnow().isoformat(),
    }
    try:
        producer = _get_producer()
        producer.send(topic, message)
        producer.flush()
    except ModuleNotFoundError:
        log.info("Kafka client not installed; skipped topic=%s", topic)
    except Exception as exc:
        log.warning("Kafka notify failed for topic=%s: %s", topic, exc)


def notify_indexing_done(doc_id: str, chunk_count: int) -> None:
    notify(settings.TOPIC_DONE, EmbeddingDone(doc_id=doc_id, chunk_count=chunk_count).model_dump(mode="json"))


def notify_indexing_failed(doc_id: str, reason: str) -> None:
    notify(settings.TOPIC_FAILED, IndexingFailed(doc_id=doc_id, reason=reason).model_dump(mode="json"))
