"""drop document_chunks table

Revision ID: a9c4e2f81b30
Revises: f7e3b1c94a02
Create Date: 2026-05-30

document_chunks was write-only: pipeline wrote to it but nothing ever read
back from it. Retrieval reads only from Qdrant (VectorStore). Dropping the
table removes dead storage and the corresponding write latency on every ingest.
"""
from alembic import op

revision = "a9c4e2f81b30"
down_revision = "f7e3b1c94a02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("document_chunks")


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported: document_chunks was write-only dead storage. "
        "To restore, re-run the full migration chain from scratch."
    )
