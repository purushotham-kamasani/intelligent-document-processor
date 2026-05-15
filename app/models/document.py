"""ORM models.

Three tables:
  * documents          — one row per uploaded file
  * stage_executions   — per-stage audit (preprocess / extract / validate / load)
  * batches            — group of documents processed together

Modeled Snowflake-style: every table has created_at, and downstream analytics
queries can join through document_id without surprises. JSON columns hold the
flexible parts (extracted_data, raw_text, error details).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.schemas.document import BatchStatus, DocumentStatus, DocumentType


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Document(Base):
    """An uploaded document and the state of its processing pipeline."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()

    # File metadata
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Classification & state
    doc_type: Mapped[DocumentType] = mapped_column(
        SAEnum(
            DocumentType,
            name="document_type",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=DocumentType.UNKNOWN,
        nullable=False,
        index=True,
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(
            DocumentStatus,
            name="document_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=DocumentStatus.UPLOADED,
        nullable=False,
        index=True,
    )

    # Extracted content
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Optional batch grouping
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stages: Mapped[list[StageExecution]] = relationship(
        "StageExecution",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="StageExecution.created_at",
        lazy="selectin",
    )
    batch: Mapped[Batch | None] = relationship("Batch", back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document id={self.id} type={self.doc_type} status={self.status}>"


class StageExecution(Base):
    """Audit record for a single pipeline stage on a single document.

    Stages: preprocess, extract, validate, load.
    """

    __tablename__ = "stage_executions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    output_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship("Document", back_populates="stages")


class Batch(Base):
    """Group of documents submitted for parallel processing."""

    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = _uuid_pk()
    status: Mapped[BatchStatus] = mapped_column(
        SAEnum(
            BatchStatus,
            name="batch_status",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=BatchStatus.PENDING,
        nullable=False,
        index=True,
    )

    total_documents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="batch",
        lazy="selectin",
    )
