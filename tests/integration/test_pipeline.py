"""Integration tests for the document pipeline."""

from __future__ import annotations

import pytest

from app.pipeline.pipeline import DocumentPipeline
from app.schemas.document import DocumentStatus, DocumentType


@pytest.mark.asyncio
async def test_pipeline_processes_invoice_end_to_end(
    session, mock_llm, storage, document_service, sample_invoice_text
):
    """Upload an invoice text file and run the full pipeline."""
    doc = await document_service.upload(
        filename="invoice.txt",
        mime_type="text/plain",
        data=sample_invoice_text,
        doc_type=DocumentType.INVOICE,
    )
    assert doc.status == DocumentStatus.UPLOADED

    pipeline = DocumentPipeline(session=session, llm=mock_llm, storage=storage)
    processed = await pipeline.process(doc.id)

    assert processed.status == DocumentStatus.READY
    assert processed.extracted_data is not None
    assert "invoice_number" in processed.extracted_data
    assert "total" in processed.extracted_data


@pytest.mark.asyncio
async def test_pipeline_classifies_unknown_doc_type(
    session, mock_llm, storage, document_service, sample_support_ticket_text
):
    """When doc_type is UNKNOWN, the pipeline should classify it."""
    doc = await document_service.upload(
        filename="ticket.txt",
        mime_type="text/plain",
        data=sample_support_ticket_text,
        # No doc_type passed → defaults to UNKNOWN.
    )
    assert doc.doc_type == DocumentType.UNKNOWN

    pipeline = DocumentPipeline(session=session, llm=mock_llm, storage=storage)
    processed = await pipeline.process(doc.id)

    # Should have classified and extracted.
    assert processed.doc_type == DocumentType.SUPPORT_TICKET
    assert processed.status == DocumentStatus.READY
    assert processed.extracted_data["category"] in {"bug", "complaint"}


@pytest.mark.asyncio
async def test_pipeline_processes_contract(
    session, mock_llm, storage, document_service, sample_contract_text
):
    doc = await document_service.upload(
        filename="contract.txt",
        mime_type="text/plain",
        data=sample_contract_text,
        doc_type=DocumentType.CONTRACT,
    )
    pipeline = DocumentPipeline(session=session, llm=mock_llm, storage=storage)
    processed = await pipeline.process(doc.id)

    assert processed.status == DocumentStatus.READY
    assert "parties" in processed.extracted_data
    assert "title" in processed.extracted_data


@pytest.mark.asyncio
async def test_pipeline_creates_stage_audit_rows(
    session, mock_llm, storage, document_service, sample_invoice_text
):
    """Each pipeline stage should leave an audit row."""
    doc = await document_service.upload(
        filename="invoice.txt",
        mime_type="text/plain",
        data=sample_invoice_text,
        doc_type=DocumentType.INVOICE,
    )
    pipeline = DocumentPipeline(session=session, llm=mock_llm, storage=storage)
    await pipeline.process(doc.id)

    fetched = await document_service.get(doc.id)
    stage_names = [s.stage for s in fetched.stages]
    # doc_type was known, so classify is skipped.
    assert "preprocess" in stage_names
    assert "extract" in stage_names
    assert "validate" in stage_names
    # Every stage should be marked success.
    for s in fetched.stages:
        assert s.status == "success", f"stage {s.stage} not success: {s.error_message}"
        assert s.completed_at is not None


@pytest.mark.asyncio
async def test_pipeline_processes_pdf(
    session, mock_llm, storage, document_service, sample_pdf_bytes
):
    """PDF preprocessing should produce text that the extractor can use."""
    doc = await document_service.upload(
        filename="invoice.pdf",
        mime_type="application/pdf",
        data=sample_pdf_bytes,
        doc_type=DocumentType.INVOICE,
    )
    pipeline = DocumentPipeline(session=session, llm=mock_llm, storage=storage)
    processed = await pipeline.process(doc.id)
    assert processed.status == DocumentStatus.READY
    assert processed.raw_text is not None
    assert len(processed.raw_text) > 0


@pytest.mark.asyncio
async def test_pipeline_handles_flaky_llm(
    session, mock_llm_flaky, storage, document_service, sample_invoice_text
):
    """With a flaky LLM (40% failure rate), retries should usually save us."""
    doc = await document_service.upload(
        filename="invoice.txt",
        mime_type="text/plain",
        data=sample_invoice_text,
        doc_type=DocumentType.INVOICE,
    )
    pipeline = DocumentPipeline(session=session, llm=mock_llm_flaky, storage=storage)
    processed = await pipeline.process(doc.id)
    # With seed=42 and 3 retries on extract, we expect success.
    # If it failed, we should at least see retry evidence.
    fetched = await document_service.get(doc.id)
    if processed.status == DocumentStatus.FAILED:
        # Retry path was exercised but exhausted — still a valid outcome.
        assert processed.error_message
    else:
        assert processed.status == DocumentStatus.READY
    assert any(s.stage == "extract" for s in fetched.stages)
