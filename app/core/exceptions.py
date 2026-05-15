"""Domain exceptions for the document processor.

These get mapped to HTTP responses by the exception handlers in main.py.
"""

from __future__ import annotations


class DocumentError(Exception):
    """Base for all document-domain errors."""


class DocumentNotFoundError(DocumentError):
    """Raised when a document ID can't be found."""


class UnsupportedDocumentTypeError(DocumentError):
    """Raised on unknown mime type or doc_type registration miss."""


class StorageError(DocumentError):
    """Raised when the storage backend (disk/S3) fails."""


class FileTooLargeError(DocumentError):
    """Raised when upload exceeds configured size cap."""


class ExtractionError(DocumentError):
    """Raised when LLM extraction fails after retries."""

    def __init__(self, document_id: str, reason: str):
        self.document_id = document_id
        self.reason = reason
        super().__init__(f"Extraction failed for {document_id}: {reason}")


class ValidationError(DocumentError):
    """Raised when extracted data doesn't conform to the doc-type schema."""

    def __init__(self, doc_type: str, errors: list[str]):
        self.doc_type = doc_type
        self.errors = errors
        super().__init__(f"Schema validation failed for {doc_type}: {errors}")


class LLMError(Exception):
    """Base for LLM errors."""


class LLMTimeoutError(LLMError):
    """LLM call exceeded timeout."""


class LLMTransientError(LLMError):
    """Retryable LLM error (rate limit, transient 5xx)."""
