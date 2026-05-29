"""drop_description

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-29

description column has no source in the current pipeline:
S3 scanner cannot populate it and no other input exists.
Removed to keep schema honest with what the system can actually produce.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("documents", "description")


def downgrade() -> None:
    op.add_column("documents", sa.Column("description", sa.Text(), nullable=True))
