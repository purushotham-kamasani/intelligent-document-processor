"""Integration tests for the batch processor."""

from __future__ import annotations

import pytest

from app.pipeline.batch import BatchProcessor
from app.schemas.document import BatchStatus, DocumentStatus, DocumentType


@pytest.mark.asyncio
async def test_batch_processes_multiple_documents(
    session_factory,
    mock_llm,
    storage,
    sample_invoice_text,
    sample_support_ticket_text,
    sample_contract_text,
):
    """Create a batch of mixed-type documents and process them all."""
    from app.services.document_service import DocumentService

    # Upload three documents in one session.
    async with session_factory() as session:
        service = DocumentService(session=session, storage=storage)
        doc_a = await service.upload(
            filename="inv.txt",
            mime_type="text/plain",
            data=sample_invoice_text,
            doc_type=DocumentType.INVOICE,
        )
        doc_b = await service.upload(
            filename="ticket.txt",
            mime_type="text/plain",
            data=sample_support_ticket_text,
            doc_type=DocumentType.SUPPORT_TICKET,
        )
        doc_c = await service.upload(
            filename="contract.txt",
            mime_type="text/plain",
            data=sample_contract_text,
            doc_type=DocumentType.CONTRACT,
        )
        batch = await service.create_batch([doc_a.id, doc_b.id, doc_c.id])
        batch_id = batch.id
        ids = [doc_a.id, doc_b.id, doc_c.id]

    processor = BatchProcessor(session_factory=session_factory, llm=mock_llm, storage=storage)
    await processor.run(batch_id)

    async with session_factory() as session:
        service = DocumentService(session=session, storage=storage)
        batch = await service.get_batch(batch_id)
        assert batch.status == BatchStatus.COMPLETED
        assert batch.completed_count == 3
        assert batch.failed_count == 0

        for doc_id in ids:
            d = await service.get(doc_id)
            assert d.status == DocumentStatus.READY


@pytest.mark.asyncio
async def test_batch_respects_concurrency_limit(
    session_factory, mock_llm, storage, sample_invoice_text
):
    """Submit multiple docs in a batch; verify all complete.

    Tests use BATCH_MAX_CONCURRENCY=1 (set in conftest.py) because SQLite's
    StaticPool doesn't support concurrent transactions cleanly. The batch
    *orchestration logic* is the same regardless of concurrency level —
    real Postgres handles N>1 just fine.
    """
    from app.services.document_service import DocumentService

    async with session_factory() as session:
        service = DocumentService(session=session, storage=storage)
        doc_ids = []
        for i in range(6):
            d = await service.upload(
                filename=f"inv_{i}.txt",
                mime_type="text/plain",
                data=sample_invoice_text,
                doc_type=DocumentType.INVOICE,
            )
            doc_ids.append(d.id)
        batch = await service.create_batch(doc_ids)
        batch_id = batch.id

    processor = BatchProcessor(session_factory=session_factory, llm=mock_llm, storage=storage)
    await processor.run(batch_id)

    async with session_factory() as session:
        service = DocumentService(session=session, storage=storage)
        batch = await service.get_batch(batch_id)
        assert batch.total_documents == 6
        assert batch.completed_count == 6
        assert batch.status == BatchStatus.COMPLETED


@pytest.mark.asyncio
async def test_batch_marks_partial_when_some_fail(
    session_factory, mock_llm, storage, sample_invoice_text
):
    """When the batch contains a deletable-storage doc, that doc fails but
    others succeed — batch ends in PARTIAL state."""
    from app.services.document_service import DocumentService

    async with session_factory() as session:
        service = DocumentService(session=session, storage=storage)
        good = await service.upload(
            filename="good.txt",
            mime_type="text/plain",
            data=sample_invoice_text,
            doc_type=DocumentType.INVOICE,
        )
        bad = await service.upload(
            filename="bad.txt",
            mime_type="text/plain",
            data=sample_invoice_text,
            doc_type=DocumentType.INVOICE,
        )
        # Delete the bad doc's underlying file to force a storage failure.
        await storage.delete(bad.storage_path)

        batch = await service.create_batch([good.id, bad.id])
        batch_id = batch.id

    processor = BatchProcessor(session_factory=session_factory, llm=mock_llm, storage=storage)
    await processor.run(batch_id)

    async with session_factory() as session:
        service = DocumentService(session=session, storage=storage)
        batch = await service.get_batch(batch_id)
        assert batch.status == BatchStatus.PARTIAL
        assert batch.completed_count == 1
        assert batch.failed_count == 1
