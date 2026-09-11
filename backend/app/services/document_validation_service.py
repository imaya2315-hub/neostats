"""
Input-control layer: persists the upload and validates type / integrity /
page count *before* any OCR or AI extraction is attempted. This is
deliberately separate from document-type classification (out of scope)
and from field extraction (extraction_service).
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.file_utils import FileValidationResult, save_upload, validate_file

logger = get_logger("docintel.validation")


def persist_and_validate(original_filename: str, content: bytes) -> tuple[str, FileValidationResult]:
    """Save the raw bytes to disk and run structural validation.

    Returns (stored_path, FileValidationResult). The stored path is
    returned even on failure where possible, so callers can still clean
    up / inspect the file if needed.
    """
    settings = get_settings()
    logger.info("Persisting upload '%s' (%d bytes)", original_filename, len(content))
    stored_path = save_upload(settings.UPLOAD_DIR, original_filename, content)

    result = validate_file(stored_path, original_filename)
    if result.status != "PASS":
        logger.warning(
            "Validation failed for '%s': %s (%s)",
            original_filename,
            result.error_code,
            result.error_message,
        )
    else:
        logger.info(
            "Validation passed for '%s': %d page(s), type=%s",
            original_filename,
            result.page_count,
            result.file_type,
        )
    return stored_path, result
