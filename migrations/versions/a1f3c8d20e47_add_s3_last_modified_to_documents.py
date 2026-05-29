"""add_s3_last_modified_to_documents

Revision ID: a1f3c8d20e47
Revises: c3ba9fa6409d
Create Date: 2026-05-29

Store the S3 LastModified timestamp so the scanner can detect file changes
correctly, instead of comparing against uploaded_at (which is DE processing
time, not the actual S3 upload time).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1f3c8d20e47"
down_revision: Union[str, Sequence[str], None] = "c3ba9fa6409d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("s3_last_modified", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "s3_last_modified")
