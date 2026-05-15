"""Document text extraction.

Handles a few common file types:
  * text/plain  — read as-is
  * application/pdf — extract via pypdf
  * application/json — flatten to a readable string

The interface is tiny on purpose. Adding a new type (.docx, .html) is
a new branch in `extract_text`.
"""

from __future__ import annotations

import io
import json

from pypdf import PdfReader

from app.core.exceptions import UnsupportedDocumentTypeError
from app.core.logging import get_logger

_logger = get_logger(__name__)


SUPPORTED_MIME_TYPES = {
    "text/plain",
    "application/pdf",
    "application/json",
    "text/markdown",
}


def extract_text(data: bytes, mime_type: str) -> str:
    """Extract a string representation of the document content."""
    mime_type = mime_type.lower()

    if mime_type in {"text/plain", "text/markdown"}:
        return data.decode("utf-8", errors="replace")

    if mime_type == "application/json":
        try:
            parsed = json.loads(data.decode("utf-8", errors="replace"))
            return _flatten_json(parsed)
        except json.JSONDecodeError as exc:
            _logger.warning("preprocess.json_decode_failed", error=str(exc))
            return data.decode("utf-8", errors="replace")

    if mime_type == "application/pdf":
        return _extract_pdf_text(data)

    raise UnsupportedDocumentTypeError(
        f"Unsupported mime type: {mime_type!r}. Supported: {sorted(SUPPORTED_MIME_TYPES)}"
    )


def _extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(pages).strip()
    except Exception as exc:
        _logger.warning("preprocess.pdf_extract_failed", error=str(exc))
        return ""


def _flatten_json(obj: object, prefix: str = "") -> str:
    """Render JSON as a readable line-per-leaf string for LLM consumption."""
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            lines.append(_flatten_json(v, key))
        return "\n".join(line for line in lines if line)
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            lines.append(_flatten_json(item, f"{prefix}[{i}]"))
        return "\n".join(line for line in lines if line)
    return f"{prefix}: {obj}"
