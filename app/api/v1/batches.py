"""Batch processing routes."""

from __future__ import annotations

import contextlib
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.api.deps import (
    get_document_service,
    get_llm_client,
    get_storage,
)
from app.core.exceptions import DocumentNotFoundError
from app.core.logging import get_logger
from app.db.session import AsyncSessionLocal
from app.llm.base import LLMClient
from app.pipeline.batch import BatchProcessor
from app.schemas.document import BatchRead, BatchSubmitRequest
from app.services.document_service import DocumentService
from app.services.storage import StorageBackend

router = APIRouter(prefix="/batches", tags=["batches"])
_logger = get_logger(__name__)


async def _run_batch_background(
    batch_id: uuid.UUID,
    session_factory: async_sessionmaker,
    llm: LLMClient,
    storage: StorageBackend,
) -> None:
    processor = BatchProcessor(session_factory=session_factory, llm=llm, storage=storage)
    try:
        await processor.run(batch_id)
    except Exception:  # pragma: no cover — defensive
        _logger.exception("batch.background_failed", batch_id=str(batch_id))


def _get_session_factory() -> async_sessionmaker:
    """Lookup test-overridable session factory.

    Centralizes the override-aware lookup so it stays consistent with
    document routes.
    """
    from app.api.deps import session_for_background
    from app.main import app as _app

    provider = _app.dependency_overrides.get(session_for_background)
    if provider is not None:
        # Tests use this path — they injected a session generator whose
        # bound engine has the test schema.

        # Walk the generator once to extract the session and reuse its bind.
        # But generators are single-use, so we wrap into a callable factory.
        async def _gen_factory():
            async for s in provider():
                return s

        # Construct a callable that returns an AsyncSession context.
        class _Factory:
            def __call__(self):
                return _ManagedSession(provider)

        return _Factory()
    return AsyncSessionLocal


class _ManagedSession:
    """Adapt a `session_for_background` async-gen into a context manager.

    The pipeline expects `async with session_factory() as session:` semantics;
    the test override yields sessions from a generator. This shim bridges
    them so batch processing works under both prod and test wiring.
    """

    def __init__(self, provider):
        self._provider = provider
        self._gen = None
        self._session = None

    async def __aenter__(self):
        self._gen = self._provider()
        self._session = await self._gen.__anext__()
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        with contextlib.suppress(Exception):  # pragma: no cover
            await self._gen.aclose()


@router.post(
    "",
    response_model=BatchRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a batch of documents for processing",
)
async def submit_batch(
    payload: BatchSubmitRequest,
    background_tasks: BackgroundTasks,
    service: DocumentService = Depends(get_document_service),
    llm: LLMClient = Depends(get_llm_client),
    storage: StorageBackend = Depends(get_storage),
) -> BatchRead:
    try:
        batch = await service.create_batch(payload.document_ids)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    session_factory = _get_session_factory()
    background_tasks.add_task(_run_batch_background, batch.id, session_factory, llm, storage)

    return BatchRead.model_validate(batch)


@router.get(
    "/{batch_id}",
    response_model=BatchRead,
    summary="Fetch batch status",
)
async def get_batch(
    batch_id: uuid.UUID,
    service: DocumentService = Depends(get_document_service),
) -> BatchRead:
    try:
        batch = await service.get_batch(batch_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return BatchRead.model_validate(batch)
