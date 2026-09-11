"""
Orchestration layer.

This is the only module that knows about the *entire* pipeline described
in the assignment:

    Upload -> Document Validation -> OCR -> AI Extraction ->
    Financial Validation -> Store -> PASS/FAILED -> API response

Every stage itself lives in its own single-responsibility service
(document_validation_service, ocr_service, extraction_service,
financial_validation_service, document_repository) so each can be unit
tested and swapped independently; this module just sequences them and
makes sure that whatever happens (validation failure, OCR failure, LLM
failure) we always end up with a persisted, well-formed structured
response instead of a raw exception reaching the API layer.
"""
from __future__ import annotations

import datetime as dt
import time

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import document_repository
from app.services import document_validation_service, financial_validation_service, ocr_service
from app.services.extraction_service import REQUIRED_FIELDS, ExtractionError, extract

logger = get_logger("docintel.orchestrator")

# Financial statements in this dataset are scanned as ruled comparative
# grids and benefit from the deterministic column-detection table
# extractor; invoices are free-form and are handled by the LLM pass only.
_EXPECTS_TABLE = {
    "invoice": False,
    "balance_sheet": True,
    "profit_and_loss": True,
    "cash_flow_statement": True,
}


def process_upload(
    db: Session, *, original_filename: str, document_type: str, content: bytes
) -> dict:
    """Run the full pipeline for one uploaded file and return the same
    structured dict shape the API/dashboard expect, regardless of where
    in the pipeline processing stopped."""
    start = time.monotonic()

    # ---- 1. Document validation (input-control layer) ----
    stored_path, file_validation = document_validation_service.persist_and_validate(
        original_filename, content
    )

    if file_validation.status != "PASS":
        return _persist_failure(
            db,
            original_filename=original_filename,
            document_type=document_type,
            file_validation=file_validation.to_dict(),
            started_at=start,
            warnings=[],
            pages_processed=0,
            ocr_used=False,
            llm_model=None,
        )

    # ---- 2. OCR / text extraction ----
    try:
        artifacts = ocr_service.process_document(
            stored_path, expects_table=_EXPECTS_TABLE.get(document_type, False)
        )
    except Exception as exc:  # noqa: BLE001 - never let OCR failures crash the request
        logger.exception("OCR failed for '%s'", original_filename)
        return _persist_failure(
            db,
            original_filename=original_filename,
            document_type=document_type,
            file_validation=file_validation.to_dict(),
            started_at=start,
            warnings=[f"OCR_FAILED: {exc}"],
            pages_processed=0,
            ocr_used=False,
            llm_model=None,
        )

    ocr_used = any(a.ocr_used for a in artifacts)

    # ---- 3. AI-based field & table extraction ----
    try:
        outcome = extract(document_type, artifacts)
    except ExtractionError as exc:
        logger.error("Extraction failed for '%s': %s", original_filename, exc)
        return _persist_failure(
            db,
            original_filename=original_filename,
            document_type=document_type,
            file_validation=file_validation.to_dict(),
            started_at=start,
            warnings=[str(exc)],
            pages_processed=len(artifacts),
            ocr_used=ocr_used,
            llm_model=None,
        )
    except Exception as exc:  # noqa: BLE001 - defend against unexpected provider errors too
        logger.exception("Unexpected extraction error for '%s'", original_filename)
        return _persist_failure(
            db,
            original_filename=original_filename,
            document_type=document_type,
            file_validation=file_validation.to_dict(),
            started_at=start,
            warnings=[f"EXTRACTION_FAILED: {exc}"],
            pages_processed=len(artifacts),
            ocr_used=ocr_used,
            llm_model=None,
        )

    # ---- 4. Financial calculation validation ----
    validation = financial_validation_service.validate(document_type, outcome.data)

    # ---- 5. Confidence + PASS/FAILED determination ----
    confidence = _compute_confidence(document_type, outcome.data, validation)
    status = _determine_status(document_type, outcome.data, validation)

    processing_metadata = {
        "ocr_used": ocr_used,
        "processed_at": _now_iso(),
        "processing_time_ms": _elapsed_ms(start),
        "pages_processed": len(artifacts),
        "llm_model": outcome.llm_model,
        "warnings": outcome.warnings,
    }

    # ---- 6. Persist ----
    record = document_repository.upsert_result(
        db,
        document_name=original_filename,
        document_type=document_type,
        processing_status=status,
        overall_confidence=confidence,
        file_validation=file_validation.to_dict(),
        extracted_data=outcome.data,
        validation=validation,
        processing_metadata=processing_metadata,
    )
    logger.info(
        "Processed '%s' (%s): status=%s confidence=%s",
        original_filename,
        document_type,
        status,
        confidence,
    )
    return _to_response(record)


def _persist_failure(
    db: Session,
    *,
    original_filename: str,
    document_type: str,
    file_validation: dict,
    started_at: float,
    warnings: list[str],
    pages_processed: int,
    ocr_used: bool,
    llm_model: str | None,
) -> dict:
    """Persist a FAILED result (bad file, OCR failure or extraction
    failure) so it still shows up in the dashboard with a clear reason,
    instead of silently vanishing."""
    processing_metadata = {
        "ocr_used": ocr_used,
        "processed_at": _now_iso(),
        "processing_time_ms": _elapsed_ms(started_at),
        "pages_processed": pages_processed,
        "llm_model": llm_model,
        "warnings": warnings,
    }
    record = document_repository.upsert_result(
        db,
        document_name=original_filename,
        document_type=document_type,
        processing_status="FAILED",
        overall_confidence=None,
        file_validation=file_validation,
        extracted_data=None,
        validation=None,
        processing_metadata=processing_metadata,
    )
    return _to_response(record)


def _compute_confidence(document_type: str, extracted_data: dict, validation: dict) -> float | None:
    """A deliberately simple, explainable confidence score (never an
    LLM-guessed number): the average of
      (a) the fraction of this document_type's minimum-required fields
          that were actually found (non-null), and
      (b) the fraction of financial-validation checks that passed,
    restricted to whichever of those two signals actually has data to
    measure. Returns None when neither signal is available.
    """
    required = REQUIRED_FIELDS.get(document_type, [])
    fields = (extracted_data or {}).get("fields", {})
    components: list[float] = []

    if required:
        found = sum(1 for name in required if (fields.get(name) or {}).get("value") is not None)
        components.append(found / len(required))

    checks = (validation or {}).get("checks", [])
    scored = [c for c in checks if c["status"] in ("PASS", "FAIL")]
    if scored:
        passed = sum(1 for c in scored if c["status"] == "PASS")
        components.append(passed / len(scored))

    if not components:
        return None
    return round(sum(components) / len(components), 4)


def _determine_status(document_type: str, extracted_data: dict, validation: dict) -> str:
    """PASS = at least one minimum-required field for this document type
    was actually extracted (an entirely empty extraction is not usable)
    AND no financial-validation check outright FAILED. NOT_APPLICABLE
    checks (missing source fields) never block a PASS on their own, per
    the assignment's definition of PASS/FAILED."""
    required = REQUIRED_FIELDS.get(document_type, [])
    fields = (extracted_data or {}).get("fields", {})
    any_required_found = any((fields.get(name) or {}).get("value") is not None for name in required)
    any_check_failed = any(c["status"] == "FAIL" for c in (validation or {}).get("checks", []))
    return "PASS" if any_required_found and not any_check_failed else "FAILED"


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="milliseconds") + "Z"


def _elapsed_ms(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


def _to_response(record) -> dict:
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
