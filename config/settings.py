from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    ai_provider: str = "auto"
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    embed_model: str = "text-embedding-3-small"
    vision_model: str = "gpt-4o"
    embedding_dim: int = 1536
    ai_request_timeout_seconds: float = 60.0
    embed_max_retries: int = 3
    embed_retry_backoff_seconds: float = 1.0
    ocr_max_retries: int = 2
    ocr_retry_backoff_seconds: float = 1.0
    allow_mock_ai_fallback: bool = True
    pdf_render_scale: float = 1.5
    pdf_ocr_max_workers: int = 4

    chunk_size: int = 512
    chunk_overlap: int = 64
    allow_tokenizer_fallback: bool = False

    vector_store: str = "qdrant"
    qdrant_host: str = "qdrant"
    qdrant_port: int = 6333
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collection: str = "documents"

    metadata_store: str = "postgres"
    database_url: str = "postgresql://rag:rag@postgres:5432/ragdb"

    s3_bucket: str = "rag-pipeline-local"
    use_s3: bool = False
    s3_endpoint: str = "http://minio:9000"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None

    kafka_bootstrap: str = "kafka:9092"
    topic_ingest: str = "DocumentUploaded"
    topic_done: str = "EmbeddingDone"
    topic_failed: str = "IndexingFailed"
    topic_permission: str = "PermissionUpdated"
    topic_dlq: str = "DocumentUploaded.DLQ"

    consumer_group_id: str = "de-ingestion-service"
    consumer_max_retries: int = 3

    scan_interval_seconds: int = 300   # S3 poll interval; 0 = disable background scanner
    scan_prefix: str = ""              # S3 key prefix to scan, e.g. "raw/"
    scan_max_workers: int = 4          # max concurrent pipeline workers per scan cycle
    scan_job_timeout_seconds: int = 900  # max wall-clock seconds per ingest job; 0 = disable
    stale_indexing_seconds: int = 3600

    search_score_threshold: float = 0.5  # minimum cosine similarity; 0.0 = disabled
    search_query_max_length: int = 2000
    search_query_cache_size: int = 256

    max_file_size_bytes: int = 200 * 1024 * 1024
    local_file_root: str | None = None
    db_pool_size: int = 5
    db_max_overflow: int = 10


_settings = Settings()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
DLQ_DIR = DATA_DIR / "dlq"
SAMPLE_DIR = DATA_DIR / "sample"
LOCAL_FILE_ROOT = Path(_settings.local_file_root).resolve() if _settings.local_file_root else BASE_DIR.resolve()


def get_path(layer: str) -> str:
    paths = {
        "raw": (RAW_DIR, f"s3://{_settings.s3_bucket}/raw"),
        "dlq": (DLQ_DIR, f"s3://{_settings.s3_bucket}/dlq"),
        "sample": (SAMPLE_DIR, f"s3://{_settings.s3_bucket}/sample"),
    }
    try:
        local_path, s3_path = paths[layer]
    except KeyError as exc:
        valid_layers = ", ".join(sorted(paths))
        raise ValueError(f"Unknown layer '{layer}'. Valid layers: {valid_layers}") from exc
    return s3_path if _settings.use_s3 else str(local_path)


AI_PROVIDER = _settings.ai_provider
AI_BASE_URL = _settings.ai_base_url
AI_API_KEY = _settings.ai_api_key
EMBED_MODEL = _settings.embed_model
VISION_MODEL = _settings.vision_model
EMBEDDING_DIM = _settings.embedding_dim
AI_REQUEST_TIMEOUT_SECONDS = _settings.ai_request_timeout_seconds
EMBED_MAX_RETRIES = _settings.embed_max_retries
EMBED_RETRY_BACKOFF_SECONDS = _settings.embed_retry_backoff_seconds
OCR_MAX_RETRIES = _settings.ocr_max_retries
OCR_RETRY_BACKOFF_SECONDS = _settings.ocr_retry_backoff_seconds
ALLOW_MOCK_AI_FALLBACK = _settings.allow_mock_ai_fallback
PDF_RENDER_SCALE = _settings.pdf_render_scale
PDF_OCR_MAX_WORKERS = _settings.pdf_ocr_max_workers

CHUNK_SIZE = _settings.chunk_size
CHUNK_OVERLAP = _settings.chunk_overlap
ALLOW_TOKENIZER_FALLBACK = _settings.allow_tokenizer_fallback

VECTOR_STORE = _settings.vector_store
QDRANT_HOST = _settings.qdrant_host
QDRANT_PORT = _settings.qdrant_port
QDRANT_URL: str | None = _settings.qdrant_url
QDRANT_API_KEY: str | None = _settings.qdrant_api_key
QDRANT_COLLECTION = _settings.qdrant_collection

METADATA_STORE = _settings.metadata_store
DB_URL = _settings.database_url

S3_BUCKET = _settings.s3_bucket
USE_S3 = _settings.use_s3
S3_ENDPOINT = _settings.s3_endpoint
AWS_ACCESS_KEY_ID: str | None = _settings.aws_access_key_id
AWS_SECRET_ACCESS_KEY: str | None = _settings.aws_secret_access_key

KAFKA_BOOTSTRAP = _settings.kafka_bootstrap
TOPIC_INGEST = _settings.topic_ingest
TOPIC_DONE = _settings.topic_done
TOPIC_FAILED = _settings.topic_failed
TOPIC_PERMISSION = _settings.topic_permission
TOPIC_DLQ = _settings.topic_dlq
CONSUMER_GROUP_ID = _settings.consumer_group_id
CONSUMER_MAX_RETRIES = _settings.consumer_max_retries
SCAN_INTERVAL_SECONDS = _settings.scan_interval_seconds
SCAN_PREFIX = _settings.scan_prefix
SCAN_MAX_WORKERS = _settings.scan_max_workers
SCAN_JOB_TIMEOUT_SECONDS = _settings.scan_job_timeout_seconds
STALE_INDEXING_SECONDS = _settings.stale_indexing_seconds
SEARCH_SCORE_THRESHOLD = _settings.search_score_threshold
SEARCH_QUERY_MAX_LENGTH = _settings.search_query_max_length
SEARCH_QUERY_CACHE_SIZE = _settings.search_query_cache_size
MAX_FILE_SIZE_BYTES = _settings.max_file_size_bytes
DB_POOL_SIZE = _settings.db_pool_size
DB_MAX_OVERFLOW = _settings.db_max_overflow


def validate_runtime_settings() -> None:
    if EMBEDDING_DIM <= 0:
        raise ValueError("EMBEDDING_DIM must be greater than 0.")
    if CHUNK_SIZE <= 0:
        raise ValueError("CHUNK_SIZE must be greater than 0.")
    if CHUNK_OVERLAP < 0:
        raise ValueError("CHUNK_OVERLAP must be greater than or equal to 0.")
    if CHUNK_OVERLAP >= CHUNK_SIZE:
        raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
    if SCAN_MAX_WORKERS <= 0:
        raise ValueError("SCAN_MAX_WORKERS must be greater than 0.")
    if SEARCH_SCORE_THRESHOLD < 0.0 or SEARCH_SCORE_THRESHOLD > 1.0:
        raise ValueError("SEARCH_SCORE_THRESHOLD must be between 0.0 and 1.0.")
    if SEARCH_QUERY_MAX_LENGTH <= 0:
        raise ValueError("SEARCH_QUERY_MAX_LENGTH must be greater than 0.")
    if SEARCH_QUERY_CACHE_SIZE <= 0:
        raise ValueError("SEARCH_QUERY_CACHE_SIZE must be greater than 0.")
    if MAX_FILE_SIZE_BYTES <= 0:
        raise ValueError("MAX_FILE_SIZE_BYTES must be greater than 0.")
    if STALE_INDEXING_SECONDS < 0:
        raise ValueError("STALE_INDEXING_SECONDS must be greater than or equal to 0.")
    if EMBED_MAX_RETRIES <= 0:
        raise ValueError("EMBED_MAX_RETRIES must be greater than 0.")
    if OCR_MAX_RETRIES <= 0:
        raise ValueError("OCR_MAX_RETRIES must be greater than 0.")
    if PDF_RENDER_SCALE <= 0:
        raise ValueError("PDF_RENDER_SCALE must be greater than 0.")
    if PDF_OCR_MAX_WORKERS <= 0:
        raise ValueError("PDF_OCR_MAX_WORKERS must be greater than 0.")
    if EMBED_RETRY_BACKOFF_SECONDS < 0 or OCR_RETRY_BACKOFF_SECONDS < 0:
        raise ValueError("Retry backoff values must be greater than or equal to 0.")
    if not LOCAL_FILE_ROOT.exists():
        raise ValueError(f"LOCAL_FILE_ROOT does not exist: {LOCAL_FILE_ROOT}")

for _path in (RAW_DIR, DLQ_DIR, SAMPLE_DIR):
    _path.mkdir(parents=True, exist_ok=True)

validate_runtime_settings()
