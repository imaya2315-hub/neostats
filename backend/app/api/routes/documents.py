"""REST API routes: process / get-by-name / list / health."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.logging import get_logger
from app.repositories import document_repository
from app.schemas.document import (
    DocumentListResponse,
    DocumentSummary,
    DocumentType,
    HealthResponse,
)
from app.services import document_service

logger = get_logger("docintel.api")
router = APIRouter()

_MAX_UPLOAD_BYTES = get_settings().MAX_UPLOAD_SIZE_MB * 1024 * 1024


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"error": {"code": code, "message": message}})


@router.get("/api/v1/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(status="ok", service=settings.APP_NAME, environment=settings.ENVIRONMENT)


@router.post("/api/v1/documents/process", tags=["documents"])
async def process_document_endpoint(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    db: Session = Depends(get_db),
):
    if not file.filename:
        return _error("MISSING_FILE_NAME", "The uploaded file must have a name.", 400)

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        return _error(
            "FILE_TOO_LARGE",
            f"File exceeds the maximum allowed size of {get_settings().MAX_UPLOAD_SIZE_MB} MB.",
            400,
        )

    try:
        result = document_service.process_upload(
            db,
            original_filename=file.filename,
            document_type=document_type.value,
            content=content,
        )
    except Exception:  # noqa: BLE001 - never leak stack traces to the client
        logger.exception("Unhandled error processing '%s'", file.filename)
        return _error("INTERNAL_ERROR", "An unexpected error occurred while processing the document.", 500)

    return result


@router.get("/api/v1/documents/{document_name}", tags=["documents"])
def get_document(document_name: str, db: Session = Depends(get_db)):
    record = document_repository.get_by_name(db, document_name)
    if record is None:
        return _error("DOCUMENT_NOT_FOUND", f"No processed result found for '{document_name}'.", 404)

    return {
        "document_name": record.document_name,
        "document_type": record.document_type,
        "processing_status": record.processing_status,
        "overall_confidence": record.overall_confidence,
        "file_validation": record.file_validation,
        "extracted_data": record.extracted_data,
        "validation": record.validation,
        "processing_metadata": record.processing_metadata,
    }


@router.get("/api/v1/documents", response_model=DocumentListResponse, tags=["documents"])
def list_documents(limit: int = 200, db: Session = Depends(get_db)) -> DocumentListResponse:
    records = document_repository.list_all(db, limit=limit)
    summaries = [
        DocumentSummary(
            document_name=r.document_name,
            document_type=r.document_type,
            processing_status=r.processing_status,
            overall_confidence=r.overall_confidence,
            processed_at=r.updated_at,
        )
        for r in records
    ]
    return DocumentListResponse(count=len(summaries), documents=summaries)
