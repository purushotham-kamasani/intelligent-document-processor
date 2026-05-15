"""Shared pytest fixtures.

Uses in-memory SQLite + StaticPool (background tasks share schema with request).
Uses a temp directory for storage so the test suite is hermetic.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["LLM_PROVIDER"] = "mock"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.api.deps import get_llm_client, get_storage, session_for_background
from app.db.session import Base, get_session
from app.llm.mock import MockLLMClient
from app.main import app
from app.services.document_service import DocumentService
from app.services.storage import LocalDiskStorage


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def mock_llm() -> MockLLMClient:
    return MockLLMClient(latency_ms=0, seed=42)


@pytest.fixture
def mock_llm_flaky() -> MockLLMClient:
    return MockLLMClient(latency_ms=0, flake_rate=0.4, seed=42)


@pytest.fixture
def storage(tmp_path) -> LocalDiskStorage:
    return LocalDiskStorage(base_path=tmp_path / "uploads")


@pytest_asyncio.fixture
async def document_service(session, storage) -> DocumentService:
    return DocumentService(session=session, storage=storage)


@pytest_asyncio.fixture
async def api_client(session_factory, mock_llm, storage) -> AsyncGenerator[AsyncClient, None]:
    async def _get_session_override():
        async with session_factory() as s:
            yield s

    async def _get_session_for_background_override():
        async with session_factory() as s:
            yield s

    def _get_llm_override():
        return mock_llm

    def _get_storage_override():
        return storage

    app.dependency_overrides[get_session] = _get_session_override
    app.dependency_overrides[session_for_background] = _get_session_for_background_override
    app.dependency_overrides[get_llm_client] = _get_llm_override
    app.dependency_overrides[get_storage] = _get_storage_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Sample documents
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_invoice_text() -> bytes:
    return (
        b"INVOICE INV-1042\n"
        b"From: Acme Consulting Inc\n"
        b"To: Globex Corp\n"
        b"Issue Date: 2024-01-15\n"
        b"Due Date: 2024-02-14\n\n"
        b"Description: Professional services\n"
        b"Subtotal: $1,000.00\n"
        b"Tax: $80.00\n"
        b"Total: $1,080.00\n"
    )


@pytest.fixture
def sample_support_ticket_text() -> bytes:
    return (
        b"From: Jane Doe\n"
        b"Email: jane@example.com\n\n"
        b"The export button is broken. Every time I click it the page crashes "
        b"with an error. This is blocking my entire workflow."
    )


@pytest.fixture
def sample_contract_text() -> bytes:
    return (
        b"Master Services Agreement\n\n"
        b"This Agreement is entered into between Acme Consulting Inc and Globex Corp "
        b"effective January 1, 2024. The parties hereby agree to the terms below."
    )


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Generate a minimal PDF for tests using reportlab."""
    try:
        from io import BytesIO

        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas as rl_canvas
    except ImportError:
        pytest.skip("reportlab not installed")

    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.drawString(72, 720, "INVOICE INV-9999")
    c.drawString(72, 700, "From: PDF Vendor LLC")
    c.drawString(72, 680, "To: Test Customer")
    c.drawString(72, 660, "Total: $499.00")
    c.showPage()
    c.save()
    return buf.getvalue()
