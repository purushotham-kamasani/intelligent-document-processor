"""Document service — upload, fetch, list."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.exceptions import (
    DocumentNotFoundError,
    FileTooLargeError,
    UnsupportedDocumentTypeError,
)
from app.core.logging import get_logger
from app.models.document import Batch, Document
from app.pipeline.preprocessor import SUPPORTED_MIME_TYPES
from app.schemas.document import BatchStatus, DocumentStatus, DocumentType
from app.services.storage import StorageBackend

_logger = get_logger(__name__)


class DocumentService:
    """Upload + lookup operations for documents (no pipeline execution)."""

    def __init__(self, session: AsyncSession, storage: StorageBackend):
        self.session = session
        self.storage = storage
        self._settings = get_settings()

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload(
        self,
        *,
        filename: str,
        mime_type: str,
        data: bytes,
        doc_type: DocumentType | None = None,
    ) -> Document:
        """Persist the file and create a Document row in UPLOADED status."""
        if mime_type.lower() not in SUPPORTED_MIME_TYPES:
            raise UnsupportedDocumentTypeError(
                f"mime type {mime_type!r} not supported. Supported: {sorted(SUPPORTED_MIME_TYPES)}"
            )
        if len(data) > self._settings.max_upload_bytes:
            raise FileTooLargeError(
                f"file is {len(data)} bytes, max is {self._settings.max_upload_bytes}"
            )
        if len(data) == 0:
            raise FileTooLargeError("file is empty")

        storage_path, sha256 = await self.storage.save(data, filename)

        document = Document(
            filename=filename,
            mime_type=mime_type.lower(),
            size_bytes=len(data),
            storage_path=storage_path,
            sha256=sha256,
            doc_type=doc_type or DocumentType.UNKNOWN,
            status=DocumentStatus.UPLOADED,
        )
        self.session.add(document)
        await self.session.commit()
        await self.session.refresh(document)
        _logger.info(
            "document.uploaded",
            id=str(document.id),
            filename=filename,
            size=len(data),
            doc_type=document.doc_type.value,
        )
        return document

    # ------------------------------------------------------------------
    # Fetch / list
    # ------------------------------------------------------------------

    async def get(self, document_id: uuid.UUID) -> Document:
        # Force a fresh load so any in-flight pipeline updates are visible.
        cached = await self.session.get(Document, document_id)
        if cached is not None:
            await self.session.refresh(cached, attribute_names=["stages"])
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.stages))
            .where(Document.id == document_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        return doc

    async def list_documents(self, limit: int = 50, offset: int = 0) -> list[Document]:
        result = await self.session.execute(
            select(Document)
            .options(selectinload(Document.stages))
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------

    async def create_batch(self, document_ids: list[uuid.UUID]) -> Batch:
        # Validate every doc exists.
        result = await self.session.execute(select(Document).where(Document.id.in_(document_ids)))
        docs: list[Document] = list(result.scalars().all())
        if len(docs) != len(document_ids):
            found = {d.id for d in docs}
            missing = [d for d in document_ids if d not in found]
            raise DocumentNotFoundError(f"Documents not found: {missing}")

        batch = Batch(
            status=BatchStatus.PENDING,
            total_documents=len(docs),
        )
        self.session.add(batch)
        await self.session.flush()  # get the id without ending the txn

        for d in docs:
            d.batch_id = batch.id
        await self.session.commit()
        await self.session.refresh(batch)
        return batch

    async def get_batch(self, batch_id: uuid.UUID) -> Batch:
        # Refresh to pick up async updates from BatchProcessor.
        cached = await self.session.get(Batch, batch_id)
        if cached is not None:
            await self.session.refresh(cached, attribute_names=["documents"])
        result = await self.session.execute(
            select(Batch).options(selectinload(Batch.documents)).where(Batch.id == batch_id)
        )
        batch = result.scalar_one_or_none()
        if batch is None:
            raise DocumentNotFoundError(f"Batch {batch_id} not found")
        return batch
