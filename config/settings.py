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

    chunk_size: int = 512
    chunk_overlap: int = 64

    vector_store: str = "chroma"
    chroma_host: str = "chroma"
    chroma_port: int = 8000
    chroma_collection: str = "documents"
    chroma_persist_dir: str = "data/chroma"

    metadata_store: str = "postgres"
    database_url: str = "postgresql://rag:rag@postgres:5432/ragdb"

    s3_bucket: str = "rag-pipeline-local"
    use_s3: bool = False
    s3_endpoint: str = "http://minio:9000"
    aws_access_key_id: str = "minioadmin"
    aws_secret_access_key: str = "minioadmin"

    kafka_bootstrap: str = "kafka:9092"
    topic_ingest: str = "DocumentUploaded"
    topic_done: str = "EmbeddingDone"
    topic_failed: str = "IndexingFailed"
    topic_permission: str = "PermissionUpdated"
    topic_dlq: str = "DocumentUploaded.DLQ"

    consumer_group_id: str = "de-ingestion-service"
    consumer_max_retries: int = 3


_settings = Settings()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
DLQ_DIR = DATA_DIR / "dlq"
SAMPLE_DIR = DATA_DIR / "sample"


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

CHUNK_SIZE = _settings.chunk_size
CHUNK_OVERLAP = _settings.chunk_overlap

VECTOR_STORE = _settings.vector_store
CHROMA_HOST = _settings.chroma_host
CHROMA_PORT = _settings.chroma_port
CHROMA_COLLECTION = _settings.chroma_collection
CHROMA_PERSIST_DIR = str((BASE_DIR / _settings.chroma_persist_dir).resolve())

METADATA_STORE = _settings.metadata_store
DB_URL = _settings.database_url

S3_BUCKET = _settings.s3_bucket
USE_S3 = _settings.use_s3
S3_ENDPOINT = _settings.s3_endpoint
AWS_ACCESS_KEY_ID = _settings.aws_access_key_id
AWS_SECRET_ACCESS_KEY = _settings.aws_secret_access_key

KAFKA_BOOTSTRAP = _settings.kafka_bootstrap
TOPIC_INGEST = _settings.topic_ingest
TOPIC_DONE = _settings.topic_done
TOPIC_FAILED = _settings.topic_failed
TOPIC_PERMISSION = _settings.topic_permission
TOPIC_DLQ = _settings.topic_dlq
CONSUMER_GROUP_ID = _settings.consumer_group_id
CONSUMER_MAX_RETRIES = _settings.consumer_max_retries

for _path in (RAW_DIR, DLQ_DIR, SAMPLE_DIR, Path(CHROMA_PERSIST_DIR)):
    _path.mkdir(parents=True, exist_ok=True)
