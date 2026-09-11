"""
Renders a validated document into per-page artifacts that downstream
extraction can use:
  * `text`      - best-effort plain text of the page (native text layer if
                  present, otherwise full-page OCR text)
  * `table`     - structured TableExtraction (label rows + per-column
                  numeric cells) when the page looks like a financial
                  statement grid; None for plain documents like invoices
  * `ocr_used`  - whether OCR (as opposed to a native text layer) was used
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

from app.utils.file_utils import get_extension
from app.utils.table_ocr import TableExtraction, extract_table

logger = logging.getLogger("docintel.ocr")

RENDER_DPI = 300


@dataclass
class PageArtifact:
    page_number: int
    text: str
    image: Image.Image | None
    table: TableExtraction | None
    ocr_used: bool


def _page_has_table_grid(image: Image.Image) -> bool:
    """Cheap heuristic: financial statements in this pipeline are rendered
    as a single full-page image with ruled column borders; invoices/receipts
    are photographs/scans without that grid. We reuse the same vertical-line
    detector used for table extraction to decide which extraction path to run."""
    from app.utils.table_ocr import _detect_column_lines
    import numpy as np

    gray = np.array(image.convert("L"))
    lines = _detect_column_lines(gray)
    return len(lines) >= 1


def process_document(path: str, expects_table: bool) -> list[PageArtifact]:
    """Produce one PageArtifact per page. `expects_table` is derived from
    the declared document_type (invoice -> False, financial statements -> True)."""
    ext = get_extension(path)
    artifacts: list[PageArtifact] = []

    if ext == ".pdf":
        with pdfplumber.open(path) as pdf:
            native_pages = []
            for page in pdf.pages:
                native_pages.append(page.extract_text() or "")
        has_native_text = any(len(t.strip()) > 20 for t in native_pages)

        if has_native_text:
            logger.info("Native text layer detected; skipping OCR for %s", path)
            for i, text in enumerate(native_pages, start=1):
                artifacts.append(PageArtifact(page_number=i, text=text, image=None, table=None, ocr_used=False))
            return artifacts

        logger.info("No native text layer; rasterizing and running OCR for %s", path)
        images = convert_from_path(path, dpi=RENDER_DPI)
        for i, image in enumerate(images, start=1):
            table = None
            if expects_table and _page_has_table_grid(image):
                try:
                    table = extract_table(image)
                except Exception:  # noqa: BLE001
                    logger.exception("Table extraction failed on page %s of %s", i, path)
            text = pytesseract.image_to_string(image, config="--psm 6")
            artifacts.append(PageArtifact(page_number=i, text=text, image=image, table=table, ocr_used=True))
        return artifacts

    # Single image document (JPG/PNG)
    image = Image.open(path)
    table = None
    if expects_table and _page_has_table_grid(image):
        try:
            table = extract_table(image)
        except Exception:  # noqa: BLE001
            logger.exception("Table extraction failed for image %s", path)
    text = pytesseract.image_to_string(image, config="--psm 6")
    artifacts.append(PageArtifact(page_number=1, text=text, image=image, table=table, ocr_used=True))
    return artifacts
