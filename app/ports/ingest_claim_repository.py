from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from app.domain.documents.models import IngestJob


class IngestClaimRepository(Protocol):
    """Claim an ingest job atomically to prevent duplicate processing."""

    @abstractmethod
    def try_claim_ingest(self, job: IngestJob) -> bool: ...
