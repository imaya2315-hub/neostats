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
import re
from dataclasses import dataclass

import numpy as np
import pdfplumber
from PIL import Image

from app.utils.file_utils import get_extension
from app.utils.table_ocr import TableExtraction, extract_table

logger = logging.getLogger("docintel.ocr")

RENDER_DPI = 200
_RAPID_OCR_INSTANCE = None


def _get_rapid_ocr():
    global _RAPID_OCR_INSTANCE
    if _RAPID_OCR_INSTANCE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _RAPID_OCR_INSTANCE = RapidOCR()
        except Exception as exc:
            logger.warning("RapidOCR could not be initialized: %s", exc)
            return None
    return _RAPID_OCR_INSTANCE


@dataclass
class PageArtifact:
    page_number: int
    text: str
    image: Image.Image | None
    table: TableExtraction | None
    ocr_used: bool


def _format_ocr_boxes(boxes: list) -> str:
    """Group OCR bounding boxes into horizontally sorted lines, preserving table columns."""
    if not boxes:
        return ""

    items = []
    for box, text, score in boxes:
        text = text.strip()
        if not text:
            continue
        xs = [pt[0] for pt in box]
        ys = [pt[1] for pt in box]
        min_x, max_x = min(xs), max(xs)
        mid_y = (min(ys) + max(ys)) / 2.0
        items.append((mid_y, min_x, max_x, text))

    items.sort(key=lambda item: item[0])
    lines: list[dict] = []
    for mid_y, min_x, max_x, text in items:
        placed = False
        for line in lines:
            if abs(line["y"] - mid_y) < 14:
                line["items"].append((min_x, max_x, text))
                line["y"] = (line["y"] * len(line["items"]) + mid_y) / (len(line["items"]) + 1)
                placed = True
                break
        if not placed:
            lines.append({"y": mid_y, "items": [(min_x, max_x, text)]})

    formatted_lines = []
    for line in lines:
        line_items = sorted(line["items"], key=lambda it: it[0])
        parts = []
        last_right = None
        for min_x, max_x, text in line_items:
            if last_right is not None:
                gap = min_x - last_right
                if gap > 25:
                    parts.append("    ")
                else:
                    parts.append(" ")
            parts.append(text)
            last_right = max_x
        formatted_lines.append("".join(parts))

    return "\n".join(formatted_lines)


def _ocr_image(image: Image.Image) -> str:
    """Run OCR on image using RapidOCR (with layout preservation) or pytesseract fallback."""
    w, h = image.size
    ocr_img = image
    if max(w, h) > 1600:
        scale = 1600.0 / max(w, h)
        ocr_img = image.resize((int(w * scale), int(h * scale)), Image.Resampling.BILINEAR)

    if ocr_img.mode != "RGB":
        ocr_img = ocr_img.convert("RGB")

    # 1. Try RapidOCR
    ocr_engine = _get_rapid_ocr()
    if ocr_engine is not None:
        try:
            res, _ = ocr_engine(np.array(ocr_img))
            if res:
                formatted = _format_ocr_boxes(res)
                if formatted.strip():
                    return formatted
        except Exception as exc:
            logger.warning("RapidOCR execution failed: %s", exc)

    # 2. Try pytesseract fallback
    try:
        import pytesseract
        text = pytesseract.image_to_string(ocr_img, config="--psm 6")
        if text.strip():
            return text
    except Exception as exc:
        logger.warning("pytesseract execution failed: %s", exc)

    return ""


def _rasterize_pdf(path: str) -> list[Image.Image]:
    """Rasterize PDF pages to PIL images using pypdfium2 with pdf2image fallback."""
    try:
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(path)
        images = []
        for page in pdf:
            # scale=2 gives ~144 DPI, fast and clear for OCR
            img = page.render(scale=2.0).to_pil()
            images.append(img)
        if images:
            return images
    except Exception as exc:
        logger.warning("pypdfium2 rasterization failed for %s: %s", path, exc)

    try:
        from pdf2image import convert_from_path
        return convert_from_path(path, dpi=RENDER_DPI)
    except Exception as exc:
        logger.error("pdf2image rasterization also failed for %s: %s", path, exc)
        raise RuntimeError(f"Failed to rasterize PDF: {exc}") from exc


def process_document(path: str, expects_table: bool) -> list[PageArtifact]:
    """Produce one PageArtifact per page."""
    ext = get_extension(path)
    artifacts: list[PageArtifact] = []

    if ext == ".pdf":
        native_pages = []
        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    native_pages.append(page.extract_text() or "")
        except Exception as exc:
            logger.warning("pdfplumber failed reading %s: %s", path, exc)

        has_native_text = any(len(t.strip()) > 20 for t in native_pages)

        if has_native_text:
            logger.info("Native text layer detected; skipping OCR for %s", path)
            for i, text in enumerate(native_pages, start=1):
                artifacts.append(PageArtifact(page_number=i, text=text, image=None, table=None, ocr_used=False))
            return artifacts

        logger.info("No native text layer; rasterizing and running OCR for %s", path)
        images = _rasterize_pdf(path)
        for i, image in enumerate(images, start=1):
            table = None
            if expects_table:
                try:
                    table = extract_table(image)
                    if table and not table.line_items:
                        table = None
                except Exception:
                    logger.exception("Table extraction failed on page %s of %s", i, path)
            text = _ocr_image(image)
            artifacts.append(PageArtifact(page_number=i, text=text, image=image, table=table, ocr_used=True))
        return artifacts

    # Single image document (JPG/PNG)
    image = Image.open(path)
    table = None
    if expects_table:
        try:
            table = extract_table(image)
            if table and not table.line_items:
                table = None
        except Exception:
            logger.exception("Table extraction failed for image %s", path)
    text = _ocr_image(image)
    artifacts.append(PageArtifact(page_number=1, text=text, image=image, table=table, ocr_used=True))
    return artifacts
