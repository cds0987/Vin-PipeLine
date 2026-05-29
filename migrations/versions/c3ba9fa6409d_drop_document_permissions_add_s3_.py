"""drop_document_permissions_add_s3_scanner_config

Revision ID: c3ba9fa6409d
Revises: db994690f60c
Create Date: 2026-05-29

DE refactored to pure vector search engine:
- Drop document_permissions table (permission logic moved to BE)
- Remove uploaded_by, org_id from documents (DE no longer tracks ownership)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3ba9fa6409d"
down_revision: Union[str, Sequence[str], None] = "db994690f60c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("document_permissions")
    op.drop_column("documents", "uploaded_by")
    op.drop_column("documents", "org_id")


def downgrade() -> None:
    op.add_column("documents", sa.Column("org_id", sa.String(), nullable=True))
    op.add_column("documents", sa.Column("uploaded_by", sa.String(), nullable=True))
    from sqlalchemy.dialects.postgresql import JSONB
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
