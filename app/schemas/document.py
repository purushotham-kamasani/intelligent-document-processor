"""Pydantic schemas — API contracts and shared enums.

Document state machine:

    uploaded → preprocessing → extracting → validating → ready
                                                 ↓
                                              failed

Doc-type schemas (Invoice, SupportTicket, Contract) are the *target shapes*
the LLM is asked to extract into. Adding a new doc type means:
  1) define its Pydantic schema here
  2) register it in app/extractors/registry.py
  3) (optional) add a routing case to the mock LLM
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Lifecycle states
# ---------------------------------------------------------------------------


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PREPROCESSING = "preprocessing"
    EXTRACTING = "extracting"
    VALIDATING = "validating"
    READY = "ready"
    FAILED = "failed"


class DocumentType(str, enum.Enum):
    """Known document types. Each maps to an extraction schema."""

    INVOICE = "invoice"
    SUPPORT_TICKET = "support_ticket"
    CONTRACT = "contract"
    UNKNOWN = "unknown"


class BatchStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"  # some docs succeeded, some failed
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Per-doc-type extraction schemas (target shapes)
# ---------------------------------------------------------------------------


class InvoiceLineItem(BaseModel):
    description: str
    quantity: float = Field(..., ge=0)
    unit_price: float = Field(..., ge=0)
    total: float = Field(..., ge=0)


class InvoiceData(BaseModel):
    """Target shape for invoice extraction."""

    invoice_number: str
    issue_date: date | None = None
    due_date: date | None = None
    vendor: str
    customer: str | None = None
    line_items: list[InvoiceLineItem] = Field(default_factory=list)
    subtotal: float = Field(..., ge=0)
    tax: float = Field(default=0.0, ge=0)
    total: float = Field(..., ge=0)
    currency: str = "USD"


class SupportTicketData(BaseModel):
    """Target shape for a support ticket."""

    ticket_id: str | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    category: str = Field(..., description="bug / question / feature_request / complaint")
    priority: str = Field(..., description="low / medium / high / urgent")
    summary: str
    sentiment: str | None = None


class ContractData(BaseModel):
    """Target shape for a basic contract extraction."""

    title: str
    parties: list[str]
    effective_date: date | None = None
    expiry_date: date | None = None
    term_months: int | None = Field(default=None, ge=1)
    governing_law: str | None = None
    key_obligations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Read / response schemas
# ---------------------------------------------------------------------------


class StageExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    stage: str
    status: str
    attempts: int
    started_at: datetime | None
    completed_at: datetime | None
    error_message: str | None


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    mime_type: str
    size_bytes: int
    doc_type: DocumentType
    status: DocumentStatus
    extracted_data: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    stages: list[StageExecutionRead] = Field(default_factory=list)


class DocumentUploadResponse(BaseModel):
    """Returned immediately after upload."""

    id: uuid.UUID
    filename: str
    status: DocumentStatus
    doc_type: DocumentType


class BatchSubmitRequest(BaseModel):
    """Submit a batch of already-uploaded documents for processing."""

    document_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)


class BatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: BatchStatus
    total_documents: int
    completed_count: int
    failed_count: int
    created_at: datetime
    completed_at: datetime | None
