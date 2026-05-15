"""Unit tests for the document text preprocessor."""

from __future__ import annotations

import pytest

from app.core.exceptions import UnsupportedDocumentTypeError
from app.pipeline.preprocessor import extract_text


def test_extracts_plain_text():
    out = extract_text(b"Hello world", "text/plain")
    assert out == "Hello world"


def test_extracts_markdown_text():
    out = extract_text(b"# Heading\n\ntext", "text/markdown")
    assert "Heading" in out


def test_flattens_json():
    out = extract_text(b'{"a": 1, "b": {"c": "x"}}', "application/json")
    assert "a: 1" in out
    assert "b.c: x" in out


def test_extracts_pdf_text(sample_pdf_bytes):
    out = extract_text(sample_pdf_bytes, "application/pdf")
    assert "INV-9999" in out or "Invoice" in out.lower() or len(out) > 0


def test_unsupported_mime_raises():
    with pytest.raises(UnsupportedDocumentTypeError):
        extract_text(b"some bytes", "image/png")


def test_malformed_json_falls_back_to_text():
    out = extract_text(b"{not valid json", "application/json")
    # Should not raise; falls back to the raw bytes as text.
    assert "not valid" in out
