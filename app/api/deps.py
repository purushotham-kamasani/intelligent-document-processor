"""FastAPI dependency providers."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import AsyncSessionLocal, get_session
from app.llm.base import LLMClient
from app.llm.factory import build_llm_client
from app.services.document_service import DocumentService
from app.services.storage import LocalDiskStorage, StorageBackend

_llm_client: LLMClient | None = None
_storage_backend: StorageBackend | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = build_llm_client()
    return _llm_client


def get_storage() -> StorageBackend:
    global _storage_backend
    if _storage_backend is None:
        _storage_backend = LocalDiskStorage(get_settings().storage_path)
    return _storage_backend


async def get_document_service(
    session: AsyncSession = Depends(get_session),
    storage: StorageBackend = Depends(get_storage),
) -> DocumentService:
    return DocumentService(session=session, storage=storage)


async def session_for_background() -> AsyncGenerator[AsyncSession, None]:
    """Fresh session for background tasks (the request session is closed by then)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
