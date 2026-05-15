"""initial schema — documents, stage_executions, batches

Revision ID: 0001_initial
Revises:
Create Date: 2025-05-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    document_type = postgresql.ENUM(
        "invoice", "support_ticket", "contract", "unknown",
        name="document_type",
        create_type=True,
    )
    document_status = postgresql.ENUM(
        "uploaded", "preprocessing", "extracting", "validating", "ready", "failed",
        name="document_status",
        create_type=True,
    )
    batch_status = postgresql.ENUM(
        "pending", "running", "completed", "partial", "failed",
        name="batch_status",
        create_type=True,
    )

    op.create_table(
        "batches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", batch_status, nullable=False, server_default="pending"),
        sa.Column("total_documents", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_batches_status", "batches", ["status"])

    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("size_bytes", sa.Integer, nullable=False),
        sa.Column("storage_path", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("doc_type", document_type, nullable=False, server_default="unknown"),
        sa.Column("status", document_status, nullable=False, server_default="uploaded"),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("extracted_data", sa.JSON, nullable=True),
        sa.Column("batch_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("batches.id", ondelete="SET NULL"), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_doc_type", "documents", ["doc_type"])
    op.create_index("ix_documents_status", "documents", ["status"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.create_index("ix_documents_batch_id", "documents", ["batch_id"])

    op.create_table(
        "stage_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_summary", sa.JSON, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_stage_executions_document_id", "stage_executions", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_stage_executions_document_id", table_name="stage_executions")
    op.drop_table("stage_executions")
    op.drop_index("ix_documents_batch_id", table_name="documents")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_index("ix_documents_doc_type", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_batches_status", table_name="batches")
    op.drop_table("batches")
    op.execute("DROP TYPE batch_status")
    op.execute("DROP TYPE document_status")
    op.execute("DROP TYPE document_type")
