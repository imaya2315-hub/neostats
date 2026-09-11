"""Request/response schemas that are not extraction-specific."""
from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    invoice = "invoice"
    balance_sheet = "balance_sheet"
    profit_and_loss = "profit_and_loss"
    cash_flow_statement = "cash_flow_statement"


class ProcessingStatus(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"


class FileValidationSchema(BaseModel):
    file_type: str
    is_supported: bool
    is_readable: bool
    page_count: int
    status: str
    error_code: str | None = None
    error_message: str | None = None


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class DocumentSummary(BaseModel):
    """One row of the dashboard list."""

    document_name: str
    document_type: str
    processing_status: str
    overall_confidence: float | None = None
    processed_at: dt.datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    count: int
    documents: list[DocumentSummary]


class HealthResponse(BaseModel):
    status: str = Field(default="ok")
    service: str
    environment: str
