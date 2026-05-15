"""FastAPI entry point."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1 import api_router
from app.core.config import get_settings
from app.core.exceptions import (
    DocumentNotFoundError,
    ExtractionError,
    FileTooLargeError,
    StorageError,
    UnsupportedDocumentTypeError,
)
from app.core.exceptions import (
    ValidationError as DomainValidationError,
)
from app.core.logging import configure_logging, get_logger

configure_logging()
_logger = get_logger(__name__)
_settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _logger.info(
        "app.startup",
        version=__version__,
        env=_settings.app_env,
        llm_provider=_settings.llm_provider,
        storage_path=str(_settings.storage_path),
    )
    yield
    _logger.info("app.shutdown")


app = FastAPI(
    title="Intelligent Document Processor",
    description=(
        "End-to-end document ingestion pipeline with LLM-assisted extraction, "
        "multi-stage workflow orchestration, schema validation, and batch processing."
    ),
    version=__version__,
    lifespan=lifespan,
    openapi_url=f"{_settings.api_v1_prefix}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _settings.is_development else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handlers
@app.exception_handler(DocumentNotFoundError)
async def _not_found(_: Request, exc: DocumentNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(UnsupportedDocumentTypeError)
async def _unsupported(_: Request, exc: UnsupportedDocumentTypeError) -> JSONResponse:
    return JSONResponse(status_code=415, content={"detail": str(exc)})


@app.exception_handler(FileTooLargeError)
async def _too_large(_: Request, exc: FileTooLargeError) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(exc)})


@app.exception_handler(StorageError)
async def _storage_error(_: Request, exc: StorageError) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": f"Storage error: {exc}"})


@app.exception_handler(DomainValidationError)
async def _validation(_: Request, exc: DomainValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Schema validation failed",
            "doc_type": exc.doc_type,
            "errors": exc.errors,
        },
    )


@app.exception_handler(ExtractionError)
async def _extraction(_: Request, exc: ExtractionError) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": "Extraction failed", "reason": exc.reason},
    )


app.include_router(api_router, prefix=_settings.api_v1_prefix)


@app.get("/health", tags=["meta"])
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "service": "intelligent-document-processor",
        "version": __version__,
        "docs": "/docs",
    }
