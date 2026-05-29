"""drop_description_from_documents

Revision ID: f7e3b1c94a02
Revises: a1f3c8d20e47
Create Date: 2026-05-29

description column has no source in the current pipeline:
S3 scanner cannot populate it and no other input exists.
Removed to keep schema honest with what the system can actually produce.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7e3b1c94a02"
down_revision: Union[str, Sequence[str], None] = "a1f3c8d20e47"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("documents", "description")


def downgrade() -> None:
    op.add_column("documents", sa.Column("description", sa.Text(), nullable=True))
