"""add_s3_last_modified

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-29

Store the S3 LastModified timestamp so the scanner can detect file changes
correctly, instead of comparing against uploaded_at (which is DE processing
time, not the actual S3 upload time).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("s3_last_modified", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "s3_last_modified")
