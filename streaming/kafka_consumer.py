from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone

from adapters.kafka_adapter import KafkaAdapter
from config import settings
from pipeline.run import run as run_pipeline
from utils.notifier import notify
from utils.storage import write_dlq_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [kafka-consumer] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _build_consumer(topic: str, group_id: str) -> KafkaConsumer:
    from kafka import KafkaConsumer

    return KafkaConsumer(
        topic,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
    )


def _send_pipeline_dlq(raw_event: dict, reason: str, attempt: int) -> None:
    now = datetime.now(timezone.utc)
    payload = {
        "event": settings.TOPIC_DLQ,
        "schema_version": raw_event.get("schema_version", "1.0"),
        "reason": "pipeline_error",
        "attempt": attempt,
        "details": reason,
        "raw": raw_event,
        "timestamp": now.isoformat(),
    }
    notify(settings.TOPIC_DLQ, payload)
    write_dlq_file(
        f"pipeline_error_{now.strftime('%Y%m%d_%H%M%S_%f')}.json",
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def process_event(raw_event: dict, retries: int | None = None) -> dict | None:
    job = KafkaAdapter().map(raw_event)
    if job is None:
        return None
    max_retries = retries or settings.CONSUMER_MAX_RETRIES
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return run_pipeline(job)
        except Exception as exc:
            last_error = exc
            log.warning("attempt=%s doc_id=%s failed: %s", attempt, job.doc_id, exc)
            time.sleep(min(attempt, 3))
    _send_pipeline_dlq(raw_event, str(last_error), max_retries)
    return None


def start(topic: str | None = None, group_id: str | None = None) -> None:
    consumer = _build_consumer(topic or settings.TOPIC_INGEST, group_id or settings.CONSUMER_GROUP_ID)
    log.info("consumer started topic=%s bootstrap=%s", topic or settings.TOPIC_INGEST, settings.KAFKA_BOOTSTRAP)
    for message in consumer:
        process_event(message.value)
        consumer.commit()


def run() -> None:
    parser = argparse.ArgumentParser(description="Consume DocumentUploaded events and run ingestion pipeline.")
    parser.add_argument("--topic", default=settings.TOPIC_INGEST)
    parser.add_argument("--group-id", default=settings.CONSUMER_GROUP_ID)
    args = parser.parse_args()
    start(topic=args.topic, group_id=args.group_id)


if __name__ == "__main__":
    run()
