"""initial_schema

Revision ID: 0001
Revises:
Create Date: 2026-05-29

Tạo toàn bộ schema ban đầu cho DE Ingestion Service:
  - documents
  - document_permissions (dropped in 0002)
  - document_chunks (dropped in 0005)
  - ingestion_jobs
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("file_type", sa.String(), nullable=True),
        sa.Column("document_type", sa.String(), nullable=False, server_default="general"),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(), nullable=False, server_default="vi"),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("uploaded_by", sa.String(), nullable=True),
        sa.Column("org_id", sa.String(), nullable=True),
        sa.Column("total_chunks", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "document_permissions",
        sa.Column("doc_id", sa.String(), primary_key=True),
        sa.Column("visibility", sa.String(), nullable=False, server_default="private"),
        sa.Column("owner_id", sa.String(), nullable=True),
        sa.Column("org_id", sa.String(), nullable=True),
        sa.Column("allowed_roles", JSONB(), nullable=False, server_default="[]"),
        sa.Column("allowed_users", JSONB(), nullable=False, server_default="[]"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "document_chunks",
        sa.Column("chunk_id", sa.String(), primary_key=True),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_document_chunks_doc_id", "document_chunks", ["doc_id"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_ingestion_jobs_doc_id", "ingestion_jobs", ["doc_id"])


def downgrade() -> None:
    op.drop_index("ix_ingestion_jobs_doc_id", table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_document_chunks_doc_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_table("document_permissions")
    op.drop_table("documents")
