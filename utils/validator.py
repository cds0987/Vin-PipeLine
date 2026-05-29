from __future__ import annotations

import json
from datetime import datetime, timezone

from pydantic import ValidationError

from config import settings
from models.events import DocumentUploaded
from utils.notifier import notify
from utils.storage import write_dlq_file


def validate_document_uploaded(raw: dict) -> DocumentUploaded | None:
    try:
        return DocumentUploaded(**raw)
    except ValidationError as exc:
        payload = {
            "event": settings.TOPIC_DLQ,
            "schema_version": raw.get("schema_version", "unknown"),
            "reason": "schema_error",
            "details": exc.errors(),
            "raw": raw,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        notify(settings.TOPIC_DLQ, payload)
        write_dlq_file(
            f"schema_error_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.json",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        return None
