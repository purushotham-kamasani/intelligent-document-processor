"""Document processing pipeline.

Per-document journey:
   uploaded → preprocess → classify → extract → validate → ready

Each stage:
  * gets its own audit row in `stage_executions`
  * runs with timeouts + bounded retries
  * advances the document.status enum

Splitting this from the API/service layer keeps the pipeline independently
testable and lets us swap in different processing strategies later (e.g.
OCR for image-based PDFs).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from string import Template
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.exceptions import (
    ExtractionError,
    LLMTransientError,
    ValidationError,
)
from app.core.logging import get_logger
from app.extractors.registry import ExtractorSpec, get_extractor
from app.llm.base import LLMClient
from app.models.document import Document, StageExecution
from app.pipeline.preprocessor import extract_text
from app.schemas.document import DocumentStatus, DocumentType
from app.services.storage import StorageBackend

_logger = get_logger(__name__)


# Stages — keep as plain strings; they go into stage_executions.stage.
STAGE_PREPROCESS = "preprocess"
STAGE_CLASSIFY = "classify"
STAGE_EXTRACT = "extract"
STAGE_VALIDATE = "validate"


class DocumentPipeline:
    """Runs the full extraction pipeline for one document."""

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMClient,
        storage: StorageBackend,
    ):
        self.session = session
        self.llm = llm
        self.storage = storage

    async def process(self, document_id: uuid.UUID) -> Document:
        """Process a single document end-to-end."""
        document = await self.session.get(Document, document_id)
        if document is None:
            raise ExtractionError(str(document_id), "document not found")

        log = _logger.bind(document_id=str(document.id), doc_type=document.doc_type.value)
        log.info("pipeline.start")

        try:
            # 1. Preprocess — read file + extract text.
            document.status = DocumentStatus.PREPROCESSING
            await self.session.commit()
            text = await self._run_stage(
                document,
                STAGE_PREPROCESS,
                self._preprocess(document),
            )

            # 2. Classify (only if doc_type is UNKNOWN) — let the LLM pick.
            if document.doc_type == DocumentType.UNKNOWN:
                inferred = await self._run_stage(
                    document,
                    STAGE_CLASSIFY,
                    self._classify(text),
                )
                document.doc_type = inferred
                await self.session.commit()
                log = log.bind(doc_type=document.doc_type.value)

            # 3. Extract — call LLM with the per-type prompt.
            document.status = DocumentStatus.EXTRACTING
            await self.session.commit()
            try:
                extractor = get_extractor(document.doc_type)
            except KeyError as exc:
                raise ExtractionError(
                    str(document.id),
                    f"No extractor for {document.doc_type}",
                ) from exc

            extracted_raw = await self._run_stage(
                document,
                STAGE_EXTRACT,
                self._extract_with_retries(text, extractor),
            )

            # 4. Validate — Pydantic conformance check.
            document.status = DocumentStatus.VALIDATING
            await self.session.commit()
            validated = await self._run_stage(
                document,
                STAGE_VALIDATE,
                self._validate(extracted_raw, extractor),
            )

            # 5. Done.
            document.extracted_data = validated
            document.status = DocumentStatus.READY
            document.completed_at = datetime.now(UTC)
            await self.session.commit()
            log.info("pipeline.completed")

        except (ExtractionError, ValidationError) as exc:
            # Re-fetch the document on a clean session state.
            await self.session.rollback()
            fresh = await self.session.get(Document, document.id)
            if fresh is not None:
                fresh.status = DocumentStatus.FAILED
                fresh.error_message = str(exc)[:1000]
                fresh.completed_at = datetime.now(UTC)
                await self.session.commit()
                document = fresh
            log.warning("pipeline.failed", reason=str(exc))
        except Exception as exc:
            await self.session.rollback()
            fresh = await self.session.get(Document, document.id)
            if fresh is not None:
                fresh.status = DocumentStatus.FAILED
                fresh.error_message = f"Unexpected error: {exc}"[:1000]
                fresh.completed_at = datetime.now(UTC)
                await self.session.commit()
                document = fresh
            log.exception("pipeline.unexpected_error")

        return document

    # ------------------------------------------------------------------
    # Stage execution wrapper — handles the audit row.
    # ------------------------------------------------------------------

    async def _run_stage(
        self,
        document: Document,
        stage_name: str,
        coro,
    ) -> Any:
        """Wrap a coroutine with an audit record.

        Resilient design: if the inner coroutine raises, we rollback first so
        the session is in a clean state, then re-attach the stage row and
        record the failure. Without this, a session left mid-transaction
        prevents us from persisting the failure audit.
        """
        stage = StageExecution(
            document_id=document.id,
            stage=stage_name,
            status="running",
            attempts=1,
            started_at=datetime.now(UTC),
        )
        self.session.add(stage)
        await self.session.commit()
        await self.session.refresh(stage)
        stage_id = stage.id

        try:
            result = await coro
        except Exception as exc:
            # Inner code may have left the session mid-transaction.
            # Roll back, then re-fetch the stage row and update it cleanly.
            await self.session.rollback()
            fresh_stage = await self.session.get(StageExecution, stage_id)
            if fresh_stage is not None:
                fresh_stage.status = "failed"
                fresh_stage.error_message = str(exc)[:1000]
                fresh_stage.completed_at = datetime.now(UTC)
                await self.session.commit()
            raise

        stage.status = "success"
        stage.completed_at = datetime.now(UTC)
        # Store a small fingerprint of the output (don't blow up the row).
        if isinstance(result, dict):
            stage.output_summary = {"keys": list(result.keys())[:20]}
        elif isinstance(result, str):
            stage.output_summary = {"length": len(result)}
        await self.session.commit()
        return result

    # ------------------------------------------------------------------
    # Stage implementations
    # ------------------------------------------------------------------

    async def _preprocess(self, document: Document) -> str:
        data = await self.storage.read(document.storage_path)
        text = extract_text(data, document.mime_type)
        document.raw_text = text[:50000]  # cap to avoid bloating the row
        await self.session.commit()
        return text

    async def _classify(self, text: str) -> DocumentType:
        prompt = (
            "Classify the following document into one of: "
            "[invoice, support_ticket, contract, unknown]. "
            "Return ONLY valid JSON: "
            '{"doc_type": "...", "confidence": 0.0-1.0}.\n\n'
            f"Text: {text[:4000]}"
        )
        response = await self.llm.complete(
            prompt,
            system="You are a document type classifier.",
            response_format="json",
        )
        try:
            parsed = json.loads(response.content)
            return DocumentType(parsed.get("doc_type", "unknown"))
        except (json.JSONDecodeError, ValueError) as exc:
            _logger.warning("classify.bad_output", error=str(exc), raw=response.content[:200])
            return DocumentType.UNKNOWN

    async def _extract_with_retries(
        self,
        text: str,
        extractor: ExtractorSpec,
    ) -> dict[str, Any]:
        """Call the LLM with the extractor's prompt, retry transient errors."""
        prompt = Template(extractor.extraction_prompt).safe_substitute(text=text[:8000])
        attempts = {"n": 0}

        async def _attempt() -> dict[str, Any]:
            attempts["n"] += 1
            response = await self.llm.complete(
                prompt,
                system=extractor.system_prompt,
                response_format="json",
            )
            try:
                return json.loads(response.content)
            except json.JSONDecodeError as exc:
                raise LLMTransientError(f"Malformed JSON: {exc.msg}") from exc

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1.5, min=1, max=10),
                retry=retry_if_exception_type(LLMTransientError),
                reraise=True,
            ):
                with attempt:
                    return await _attempt()
        except RetryError as exc:
            raise ExtractionError(
                "<runtime>",
                f"Failed after {attempts['n']} attempts: {exc}",
            ) from exc
        # Unreachable in practice — appease type checkers.
        raise ExtractionError("<runtime>", "extraction loop exited without result")

    async def _validate(
        self,
        raw: dict[str, Any],
        extractor: ExtractorSpec,
    ) -> dict[str, Any]:
        """Validate extracted data against the doc-type schema."""
        try:
            instance: BaseModel = extractor.schema.model_validate(raw)
        except PydanticValidationError as exc:
            errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
            raise ValidationError(extractor.doc_type.value, errors) from exc
        return instance.model_dump(mode="json")
