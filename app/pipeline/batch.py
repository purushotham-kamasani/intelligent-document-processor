"""Batch processor — process N documents in parallel with bounded concurrency.

Uses asyncio.Semaphore to cap concurrent LLM calls. Real systems would scale
this out via worker queues (see the event-driven sibling repo), but for
single-instance demos this is plenty.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.models.document import Batch, Document
from app.pipeline.pipeline import DocumentPipeline
from app.schemas.document import BatchStatus, DocumentStatus
from app.services.storage import StorageBackend

_logger = get_logger(__name__)


class BatchProcessor:
    """Drives a Batch through bounded-concurrency processing."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        llm: LLMClient,
        storage: StorageBackend,
    ):
        self.session_factory = session_factory
        self.llm = llm
        self.storage = storage
        self._settings = get_settings()

    async def run(self, batch_id: uuid.UUID) -> None:
        """Process every document in the batch with bounded concurrency."""
        log = _logger.bind(batch_id=str(batch_id))

        # Load batch + document IDs in one session, then close it.
        async with self.session_factory() as session:
            batch = await session.get(Batch, batch_id)
            if batch is None:
                log.error("batch.not_found")
                return
            batch.status = BatchStatus.RUNNING
            await session.commit()
            doc_ids = [d.id for d in batch.documents]

        log.info("batch.start", total=len(doc_ids))

        sem = asyncio.Semaphore(self._settings.batch_max_concurrency)

        async def _process_one(doc_id: uuid.UUID) -> bool:
            """Process one document. Returns True on success."""
            # sem bounds concurrent docs; each doc gets its own session so one
            # slow doc doesn't hold the others' transactions open.
            async with sem, self.session_factory() as session:
                pipeline = DocumentPipeline(session, self.llm, self.storage)
                try:
                    await asyncio.wait_for(
                        pipeline.process(doc_id),
                        timeout=self._settings.batch_document_timeout_seconds,
                    )
                except (TimeoutError, Exception) as exc:
                    log.warning("batch.doc_failed", document_id=str(doc_id), error=str(exc))
                    return False

                # Re-load to check final status.
                doc = await session.get(Document, doc_id)
                return doc is not None and doc.status == DocumentStatus.READY

        results = await asyncio.gather(*(_process_one(d) for d in doc_ids), return_exceptions=False)
        completed = sum(1 for r in results if r)
        failed = len(results) - completed

        # Final batch update.
        async with self.session_factory() as session:
            batch = await session.get(Batch, batch_id)
            if batch is None:
                return
            batch.completed_count = completed
            batch.failed_count = failed
            batch.completed_at = datetime.now(UTC)
            if failed == 0:
                batch.status = BatchStatus.COMPLETED
            elif completed == 0:
                batch.status = BatchStatus.FAILED
            else:
                batch.status = BatchStatus.PARTIAL
            await session.commit()

        log.info("batch.completed", completed=completed, failed=failed)
