# Re-exports for backward compatibility.
# Canonical locations: document_repository.py, ingest_claim_repository.py, job_log_repository.py
from app.ports.document_repository import DocumentRepository
from app.ports.ingest_claim_repository import IngestClaimRepository
from app.ports.job_log_repository import JobLogRepository

__all__ = ["DocumentRepository", "IngestClaimRepository", "JobLogRepository"]
