"""Low-level file helpers: type sniffing, PDF page counting, safe saving."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

import pdfplumber
from PIL import Image

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MIME_MAP = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}
MAX_PAGES = 3


@dataclass
class FileValidationResult:
    file_type: str
    is_supported: bool
    is_readable: bool
    page_count: int
    status: str
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict:
        data = {
            "file_type": self.file_type,
            "is_supported": self.is_supported,
            "is_readable": self.is_readable,
            "page_count": self.page_count,
            "status": self.status,
        }
        # Only surface error fields when there actually was an error, to
        # match the assignment's PASS-case example response exactly.
        if self.error_code:
            data["error_code"] = self.error_code
            data["error_message"] = self.error_message
        return data


def get_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def sniff_mime(extension: str) -> str:
    return MIME_MAP.get(extension, "application/octet-stream")


def save_upload(dest_dir: str, original_filename: str, content: bytes) -> str:
    """Persist the uploaded bytes under a collision-safe name and return the path."""
    os.makedirs(dest_dir, exist_ok=True)
    ext = get_extension(original_filename)
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(dest_dir, safe_name)
    with open(dest_path, "wb") as fh:
        fh.write(content)
    return dest_path


def validate_file(path: str, original_filename: str) -> FileValidationResult:
    """Validate type, integrity and page-count before any OCR/extraction runs."""
    ext = get_extension(original_filename)
    mime = sniff_mime(ext)

    if ext not in SUPPORTED_EXTENSIONS:
        return FileValidationResult(
            file_type=mime,
            is_supported=False,
            is_readable=False,
            page_count=0,
            status="FAILED",
            error_code="UNSUPPORTED_FILE_TYPE",
            error_message="Only PDF / JPG / PNG documents are supported.",
        )

    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return FileValidationResult(
            file_type=mime,
            is_supported=True,
            is_readable=False,
            page_count=0,
            status="FAILED",
            error_code="EMPTY_FILE",
            error_message="The uploaded file is empty.",
        )

    try:
        if ext == ".pdf":
            with pdfplumber.open(path) as pdf:
                page_count = len(pdf.pages)
            if page_count == 0:
                raise ValueError("PDF has no pages")
        else:
            with Image.open(path) as img:
                img.verify()
            page_count = 1
    except Exception as exc:  # noqa: BLE001 - we want to catch any parser failure
        return FileValidationResult(
            file_type=mime,
            is_supported=True,
            is_readable=False,
            page_count=0,
            status="FAILED",
            error_code="CORRUPTED_FILE",
            error_message=f"The file could not be read/parsed: {exc}",
        )

    if page_count > MAX_PAGES:
        return FileValidationResult(
            file_type=mime,
            is_supported=True,
            is_readable=True,
            page_count=page_count,
            status="FAILED",
            error_code="PAGE_LIMIT_EXCEEDED",
            error_message=f"Document has {page_count} pages; maximum supported is {MAX_PAGES}.",
        )

    return FileValidationResult(
        file_type=mime,
        is_supported=True,
        is_readable=True,
        page_count=page_count,
        status="PASS",
    )
