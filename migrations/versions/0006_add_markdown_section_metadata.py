"""add_markdown_section_metadata

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-30

Add section-centric metadata columns required by the Markdown-Section-Caption
retrieval architecture while keeping legacy total_chunks/chunk_count fields
available for compatibility.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("section_count", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("markdown_s3_uri", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("source_s3_uri", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("parser_version", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("caption_model", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("embedding_model", sa.String(), nullable=True))


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported: section-centric metadata is required by the "
        "new Markdown-Section-Caption retrieval architecture."
    )
