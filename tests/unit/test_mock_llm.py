"""Unit tests for the mock LLM client."""

from __future__ import annotations

import json

import pytest

from app.core.exceptions import LLMTransientError
from app.llm.mock import MockLLMClient


@pytest.mark.asyncio
async def test_mock_returns_response():
    llm = MockLLMClient(latency_ms=0)
    resp = await llm.complete("hello")
    assert resp.content
    assert resp.model == "mock-gpt-4o-mini"
    assert resp.metadata["simulated"] is True


@pytest.mark.asyncio
async def test_mock_classifies_invoice():
    llm = MockLLMClient(latency_ms=0)
    resp = await llm.complete(
        "Classify the following document type. Text: INVOICE INV-001 Subtotal: $100",
        system="You are a document type classifier.",
        response_format="json",
    )
    parsed = json.loads(resp.content)
    assert parsed["doc_type"] == "invoice"


@pytest.mark.asyncio
async def test_mock_classifies_support_ticket():
    llm = MockLLMClient(latency_ms=0)
    resp = await llm.complete(
        "Classify the document type. Text: My app is broken, doesn't work.",
        system="You are a document type classifier.",
        response_format="json",
    )
    parsed = json.loads(resp.content)
    assert parsed["doc_type"] == "support_ticket"


@pytest.mark.asyncio
async def test_mock_extracts_invoice_fields():
    llm = MockLLMClient(latency_ms=0)
    resp = await llm.complete(
        "Extract invoice data. Document: INVOICE INV-1042\nFrom: Acme Inc\nTotal: $1080.00",
        system="extractor for invoice",
        response_format="json",
    )
    parsed = json.loads(resp.content)
    assert "invoice_number" in parsed
    assert "vendor" in parsed
    assert "total" in parsed


@pytest.mark.asyncio
async def test_mock_extracts_support_ticket():
    llm = MockLLMClient(latency_ms=0)
    resp = await llm.complete(
        "Extract support ticket fields. Body: The export button is broken and crashes.",
        system="extractor for support ticket",
        response_format="json",
    )
    parsed = json.loads(resp.content)
    assert parsed["category"] in {"bug", "complaint"}
    assert "priority" in parsed
    assert "summary" in parsed


@pytest.mark.asyncio
async def test_mock_flaky_raises_transient():
    llm = MockLLMClient(latency_ms=0, flake_rate=1.0)
    with pytest.raises(LLMTransientError):
        await llm.complete("anything")


@pytest.mark.asyncio
async def test_mock_deterministic_with_seed():
    llm1 = MockLLMClient(latency_ms=0, flake_rate=0.5, seed=42)
    llm2 = MockLLMClient(latency_ms=0, flake_rate=0.5, seed=42)
    r1, r2 = [], []
    for _ in range(5):
        try:
            await llm1.complete("test")
            r1.append("ok")
        except LLMTransientError:
            r1.append("flake")
        try:
            await llm2.complete("test")
            r2.append("ok")
        except LLMTransientError:
            r2.append("flake")
    assert r1 == r2
