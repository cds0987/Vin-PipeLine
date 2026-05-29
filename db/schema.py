"""
Single source of truth cho PostgreSQL schema.

SQLMetadataStore import tables từ đây.
Alembic env.py import `metadata` từ đây để autogenerate migrations.

Thêm column / table mới ở đây → chạy:
    alembic revision --autogenerate -m "mô tả thay đổi"
    alembic upgrade head
"""
from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    Text,
)

metadata = MetaData()

documents = Table(
    "documents",
    metadata,
    Column("id", String, primary_key=True),
    Column("file_path", String, nullable=False),
    Column("file_name", String),
    Column("file_type", String),
    Column("document_type", String, nullable=False, server_default="general"),
    Column("title", String),
    Column("language", String, nullable=False, server_default="vi"),
    Column("status", String, nullable=False, server_default="pending"),
    Column("total_chunks", Integer),
    Column("s3_last_modified", DateTime),
    Column("uploaded_at", DateTime, nullable=False),
    Column("processed_at", DateTime),
    Column("updated_at", DateTime, nullable=False),
)

ingestion_jobs = Table(
    "ingestion_jobs",
    metadata,
    Column("id", String, primary_key=True),
    Column("doc_id", String, nullable=False),
    Column("status", String, nullable=False),
    Column("chunk_count", Integer, nullable=False, server_default="0"),
    Column("embedding_model", String),
    Column("duration_seconds", Float),
    Column("error_message", Text),
    Column("started_at", DateTime, nullable=False),
    Column("finished_at", DateTime),
)
