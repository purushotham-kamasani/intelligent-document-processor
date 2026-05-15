"""Extractor registry.

Each doc type has:
  * a Pydantic schema (the target shape)
  * an extraction prompt template (how we ask the LLM)
  * a classification hint (used by the mock LLM to route)

Adding a new doc type means adding an entry here. The pipeline and the API
don't need to change.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from app.schemas.document import (
    ContractData,
    DocumentType,
    InvoiceData,
    SupportTicketData,
)


@dataclass(frozen=True)
class ExtractorSpec:
    doc_type: DocumentType
    schema: type[BaseModel]
    extraction_prompt: str  # uses $text for the document body
    system_prompt: str


_INVOICE_EXTRACTION_PROMPT = (
    "Extract the structured invoice data from the following document. "
    "Return ONLY valid JSON matching this shape: "
    '{"invoice_number": "...", "issue_date": "YYYY-MM-DD", "due_date": "YYYY-MM-DD", '
    '"vendor": "...", "customer": "...", "line_items": [...], '
    '"subtotal": 0.0, "tax": 0.0, "total": 0.0, "currency": "USD"}.\n\n'
    "Document:\n$text"
)

_SUPPORT_TICKET_PROMPT = (
    "Extract the structured support ticket fields from the following message. "
    "Return ONLY valid JSON: "
    '{"ticket_id": null|"...", "customer_name": ..., "customer_email": ..., '
    '"category": "bug|question|feature_request|complaint", '
    '"priority": "low|medium|high|urgent", "summary": "...", "sentiment": "..."}.\n\n'
    "Body:\n$text"
)

_CONTRACT_PROMPT = (
    "Extract contract metadata from the document below. "
    "Return ONLY valid JSON: "
    '{"title": "...", "parties": [...], "effective_date": "YYYY-MM-DD", '
    '"expiry_date": "YYYY-MM-DD", "term_months": 12, '
    '"governing_law": "...", "key_obligations": [...]}.\n\n'
    "Document:\n$text"
)


_REGISTRY: dict[DocumentType, ExtractorSpec] = {
    DocumentType.INVOICE: ExtractorSpec(
        doc_type=DocumentType.INVOICE,
        schema=InvoiceData,
        extraction_prompt=_INVOICE_EXTRACTION_PROMPT,
        system_prompt="You are a precise data extractor for invoice documents.",
    ),
    DocumentType.SUPPORT_TICKET: ExtractorSpec(
        doc_type=DocumentType.SUPPORT_TICKET,
        schema=SupportTicketData,
        extraction_prompt=_SUPPORT_TICKET_PROMPT,
        system_prompt="You are a precise data extractor for customer support tickets.",
    ),
    DocumentType.CONTRACT: ExtractorSpec(
        doc_type=DocumentType.CONTRACT,
        schema=ContractData,
        extraction_prompt=_CONTRACT_PROMPT,
        system_prompt="You are a precise data extractor for legal contract documents.",
    ),
}


def get_extractor(doc_type: DocumentType) -> ExtractorSpec:
    """Return the extractor for a doc type, or raise KeyError."""
    if doc_type not in _REGISTRY:
        raise KeyError(f"No extractor registered for doc type: {doc_type}")
    return _REGISTRY[doc_type]


def list_supported_doc_types() -> list[DocumentType]:
    """List every doc type with a registered extractor."""
    return list(_REGISTRY.keys())
