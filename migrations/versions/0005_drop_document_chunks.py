"""drop_document_chunks

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-30

document_chunks was write-only: pipeline wrote to it on every ingest but
nothing ever read back from it. Retrieval reads only from Qdrant (VectorStore).
Dropping the table removes dead storage and the corresponding write latency
on every ingest.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_document_chunks_doc_id", table_name="document_chunks")
    op.drop_table("document_chunks")


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported: document_chunks was write-only dead storage. "
        "To restore, re-run the full migration chain from scratch."
    )
