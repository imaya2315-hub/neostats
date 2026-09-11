"""
Data-access layer for processed documents. Keeps SQLAlchemy specifics out
of the service/orchestration layer so the storage backend can change
(SQLite -> Postgres/MySQL) without touching business logic.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.document import ProcessedDocument


def upsert_result(
    db: Session,
    *,
    document_name: str,
    document_type: str,
    processing_status: str,
    overall_confidence: float | None,
    file_validation: dict,
    extracted_data: dict | None,
    validation: dict | None,
    processing_metadata: dict,
) -> ProcessedDocument:
    """Insert a new record, or overwrite the existing one for this
    document_name so GET-by-name always returns the latest result."""
    existing = db.execute(
        select(ProcessedDocument).where(ProcessedDocument.document_name == document_name)
    ).scalar_one_or_none()

    if existing is None:
        existing = ProcessedDocument(document_name=document_name)
        db.add(existing)

    existing.document_type = document_type
    existing.processing_status = processing_status
    existing.overall_confidence = overall_confidence
    existing.file_validation = file_validation
    existing.extracted_data = extracted_data
    existing.validation = validation
    existing.processing_metadata = processing_metadata

    db.commit()
    db.refresh(existing)
    return existing


def get_by_name(db: Session, document_name: str) -> ProcessedDocument | None:
    return db.execute(
        select(ProcessedDocument).where(ProcessedDocument.document_name == document_name)
    ).scalar_one_or_none()


def list_all(db: Session, limit: int = 200) -> list[ProcessedDocument]:
    stmt = select(ProcessedDocument).order_by(ProcessedDocument.updated_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())
