"""Unit tests for the extractor registry."""

from __future__ import annotations

import pytest

from app.extractors.registry import get_extractor, list_supported_doc_types
from app.schemas.document import DocumentType


def test_registered_types():
    types = list_supported_doc_types()
    assert DocumentType.INVOICE in types
    assert DocumentType.SUPPORT_TICKET in types
    assert DocumentType.CONTRACT in types


def test_get_extractor_returns_spec():
    spec = get_extractor(DocumentType.INVOICE)
    assert spec.doc_type == DocumentType.INVOICE
    assert spec.schema.__name__ == "InvoiceData"
    assert "$text" in spec.extraction_prompt


def test_get_extractor_unknown_raises():
    with pytest.raises(KeyError):
        get_extractor(DocumentType.UNKNOWN)
