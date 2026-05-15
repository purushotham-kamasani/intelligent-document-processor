"""HTTP-level integration tests."""

from __future__ import annotations

import asyncio
import uuid

import pytest


@pytest.mark.asyncio
async def test_healthcheck(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_root(api_client):
    response = await api_client.get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "intelligent-document-processor"


@pytest.mark.asyncio
async def test_list_supported_doc_types(api_client):
    response = await api_client.get("/v1/documents/types")
    assert response.status_code == 200
    body = response.json()
    assert "invoice" in body
    assert "support_ticket" in body
    assert "contract" in body


@pytest.mark.asyncio
async def test_upload_invoice_returns_202(api_client, sample_invoice_text):
    response = await api_client.post(
        "/v1/documents",
        files={"file": ("invoice.txt", sample_invoice_text, "text/plain")},
        data={"doc_type": "invoice", "auto_process": "false"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["filename"] == "invoice.txt"
    assert body["doc_type"] == "invoice"
    assert body["status"] == "uploaded"
    assert "id" in body


@pytest.mark.asyncio
async def test_upload_then_poll_until_ready(api_client, sample_invoice_text):
    response = await api_client.post(
        "/v1/documents",
        files={"file": ("invoice.txt", sample_invoice_text, "text/plain")},
        data={"doc_type": "invoice", "auto_process": "true"},
    )
    assert response.status_code == 202
    doc_id = response.json()["id"]

    final_status = None
    for _ in range(30):
        await asyncio.sleep(0.1)
        r = await api_client.get(f"/v1/documents/{doc_id}")
        assert r.status_code == 200
        body = r.json()
        if body["status"] in ("ready", "failed"):
            final_status = body["status"]
            break

    assert final_status == "ready", f"document did not finish: {final_status}"


@pytest.mark.asyncio
async def test_upload_unsupported_mime_returns_415(api_client):
    response = await api_client.post(
        "/v1/documents",
        files={"file": ("test.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )
    assert response.status_code == 415


@pytest.mark.asyncio
async def test_upload_empty_file_returns_413(api_client):
    response = await api_client.post(
        "/v1/documents",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_get_nonexistent_returns_404(api_client):
    response = await api_client.get(f"/v1/documents/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_documents(api_client, sample_invoice_text):
    # Seed a couple of docs.
    for _ in range(3):
        await api_client.post(
            "/v1/documents",
            files={"file": ("inv.txt", sample_invoice_text, "text/plain")},
            data={"doc_type": "invoice", "auto_process": "false"},
        )
    response = await api_client.get("/v1/documents?limit=10")
    assert response.status_code == 200
    assert len(response.json()) >= 3


@pytest.mark.asyncio
async def test_process_endpoint_kicks_off_pipeline(api_client, sample_support_ticket_text):
    """Upload with auto_process=false, then explicitly trigger processing."""
    up = await api_client.post(
        "/v1/documents",
        files={"file": ("ticket.txt", sample_support_ticket_text, "text/plain")},
        data={"doc_type": "support_ticket", "auto_process": "false"},
    )
    doc_id = up.json()["id"]

    proc = await api_client.post(f"/v1/documents/{doc_id}/process")
    assert proc.status_code == 202

    # Poll for completion.
    final = None
    for _ in range(30):
        await asyncio.sleep(0.1)
        r = await api_client.get(f"/v1/documents/{doc_id}")
        if r.json()["status"] in ("ready", "failed"):
            final = r.json()["status"]
            break
    assert final == "ready"


@pytest.mark.asyncio
async def test_cannot_reprocess_completed_doc(api_client, sample_invoice_text):
    """Trying to /process a ready document should 409."""
    up = await api_client.post(
        "/v1/documents",
        files={"file": ("inv.txt", sample_invoice_text, "text/plain")},
        data={"doc_type": "invoice", "auto_process": "true"},
    )
    doc_id = up.json()["id"]

    # Wait for completion.
    for _ in range(30):
        await asyncio.sleep(0.1)
        r = await api_client.get(f"/v1/documents/{doc_id}")
        if r.json()["status"] == "ready":
            break

    re_proc = await api_client.post(f"/v1/documents/{doc_id}/process")
    assert re_proc.status_code == 409
