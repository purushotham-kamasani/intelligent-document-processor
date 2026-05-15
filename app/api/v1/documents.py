"""Document API routes.

POST /v1/documents              — upload + (optionally) auto-process
GET  /v1/documents/{id}         — fetch with stage history
GET  /v1/documents              — list
POST /v1/documents/{id}/process — kick off processing for an uploaded doc
GET  /v1/documents/types        — supported doc types
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from app.api.deps import (
    get_document_service,
    get_llm_client,
    get_storage,
    session_for_background,
)
from app.core.exceptions import (
    DocumentNotFoundError,
    FileTooLargeError,
    UnsupportedDocumentTypeError,
)
from app.core.logging import get_logger
from app.extractors.registry import list_supported_doc_types
from app.llm.base import LLMClient
from app.pipeline.pipeline import DocumentPipeline
from app.schemas.document import (
    DocumentRead,
    DocumentStatus,
    DocumentType,
    DocumentUploadResponse,
)
from app.services.document_service import DocumentService
from app.services.storage import StorageBackend

router = APIRouter(prefix="/documents", tags=["documents"])
_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Background task — process a single document.
# Uses dependency_overrides for the session factory in tests.
# ---------------------------------------------------------------------------


async def _process_document_background(
    document_id: uuid.UUID,
    llm: LLMClient,
    storage: StorageBackend,
) -> None:
    from app.main import app as _app

    provider = _app.dependency_overrides.get(session_for_background, session_for_background)
    async for session in provider():
        pipeline = DocumentPipeline(session=session, llm=llm, storage=storage)
        try:
            await pipeline.process(document_id)
        except Exception:  # pragma: no cover — defensive
            _logger.exception("document.background_process_failed", document_id=str(document_id))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a document",
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    doc_type: DocumentType | None = Form(default=None),
    auto_process: bool = Form(default=True),
    service: DocumentService = Depends(get_document_service),
    llm: LLMClient = Depends(get_llm_client),
    storage: StorageBackend = Depends(get_storage),
) -> DocumentUploadResponse:
    """Upload a document. By default, processing kicks off in the background."""
    try:
        data = await file.read()
        document = await service.upload(
            filename=file.filename or "unnamed",
            mime_type=file.content_type or "application/octet-stream",
            data=data,
            doc_type=doc_type,
        )
    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except FileTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

    if auto_process:
        background_tasks.add_task(_process_document_background, document.id, llm, storage)

    return DocumentUploadResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        doc_type=document.doc_type,
    )


@router.post(
    "/{document_id}/process",
    response_model=DocumentRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Process a previously uploaded document",
)
async def process_document(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    service: DocumentService = Depends(get_document_service),
    llm: LLMClient = Depends(get_llm_client),
    storage: StorageBackend = Depends(get_storage),
) -> DocumentRead:
    try:
        doc = await service.get(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if doc.status not in {DocumentStatus.UPLOADED, DocumentStatus.FAILED}:
        raise HTTPException(
            status_code=409,
            detail=f"Document is in status {doc.status.value!r}; cannot re-process",
        )

    background_tasks.add_task(_process_document_background, document_id, llm, storage)
    return DocumentRead.model_validate(doc)


@router.get(
    "/types",
    response_model=list[str],
    summary="List supported document types",
)
async def list_doc_types() -> list[str]:
    return [t.value for t in list_supported_doc_types()]


@router.get(
    "/{document_id}",
    response_model=DocumentRead,
    summary="Fetch a document and its processing history",
)
async def get_document(
    document_id: uuid.UUID,
    service: DocumentService = Depends(get_document_service),
) -> DocumentRead:
    try:
        doc = await service.get(document_id)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentRead.model_validate(doc)


@router.get(
    "",
    response_model=list[DocumentRead],
    summary="List documents (newest first)",
)
async def list_documents(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: DocumentService = Depends(get_document_service),
) -> list[DocumentRead]:
    docs = await service.list_documents(limit=limit, offset=offset)
    return [DocumentRead.model_validate(d) for d in docs]
