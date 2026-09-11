"""
Schemas for the extraction/validation portion of the structured response.

Extracted fields are intentionally a flexible dict of `field_name ->
ExtractedField` rather than a fixed set of attributes, because the
assignment requires capturing *all* meaningful fields in a document, not
just the minimum list per document type. The minimum-required fields are
still guaranteed to be present (as null when not found) by the extraction
service for each document type.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class Evidence(BaseModel):
    source_text: str | None = None
    page_number: int | None = None


class ExtractedField(BaseModel):
    value: Any = None
    confidence: float | None = None  # optional, only set when meaningful
    page_number: int | None = None
    source_text: str | None = None


class LineItem(BaseModel):
    """One row of an invoice line-item table."""

    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    page_number: int | None = None


class StatementLineItem(BaseModel):
    """One row of a financial-statement table (balance sheet / P&L / cash flow)."""

    label: str
    schedule: str | None = None
    values: dict[str, float | None] = {}  # period_header -> numeric value
    page_number: int | None = None


class ExtractedData(BaseModel):
    fields: dict[str, ExtractedField] = {}
    line_items: list[LineItem] = []
    statement_line_items: list[StatementLineItem] = []
    period_headers: list[str] = []


class ValidationCheck(BaseModel):
    name: str
    formula: str
    operands: dict[str, float | None] = {}
    calculated_value: float | None = None
    reported_value: float | None = None
    variance: float | None = None
    status: str  # PASS | FAIL | NOT_APPLICABLE
    period: str | None = None
    message: str | None = None


class ValidationResult(BaseModel):
    checks: list[ValidationCheck] = []
    overall_status: str  # PASS | FAIL | NOT_APPLICABLE
    issues: list[str] = []


class ProcessingMetadata(BaseModel):
    ocr_used: bool
    processed_at: str
    processing_time_ms: int
    pages_processed: int = 0
    llm_model: str | None = None
    warnings: list[str] = []


class DocumentProcessResponse(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    overall_confidence: float | None = None
    file_validation: dict
    extracted_data: dict | None = None
    validation: dict | None = None
    processing_metadata: dict
