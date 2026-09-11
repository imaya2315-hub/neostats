"""
ORM model for a processed document. Structured, variable-shape payloads
(extracted fields, validation checks, file validation, metadata) are
stored as JSON columns since their internal shape differs by document
type; the queryable/dashboard columns (name, type, status, timestamps)
are first-class columns for fast listing/filtering.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base


class ProcessedDocument(Base):
    __tablename__ = "processed_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Latest-wins-by-name: document_name is unique, re-processing the same
    # file name overwrites this row rather than creating a duplicate.
    document_name: Mapped[str] = mapped_column(String(512), unique=True, index=True, nullable=False)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(16), nullable=False)
    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    file_validation: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processing_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow
    )
