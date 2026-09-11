"""
Table-aware OCR helpers for scanned financial statements (balance sheet,
P&L, cash flow). These documents are typically two-column comparative
statements (current period vs prior period) rendered as a single scanned
image per page, so a plain full-page OCR pass tends to merge or drop one
of the numeric columns.

Strategy:
1. Render the PDF page (or open the image) at high DPI.
2. Detect vertical table border lines to split the page into a label
   band and one band per numeric period column.
3. OCR the label band with a "variable line height" page-segmentation
   mode to get one (y-position, text) row per statement line item.
4. For every label row, crop the *same* y-range out of each numeric band
   and OCR just that small cell with a digit whitelist. This is far more
   reliable than OCR-ing an entire multi-column table in one pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pytesseract
from PIL import Image

NUMBER_RE = re.compile(r"[\d][\d,]*\.?\d*")


@dataclass
class LineItem:
    label: str
    schedule: str | None
    values: list[str | None]  # one entry per detected numeric column, raw OCR text
    y: int


@dataclass
class TableExtraction:
    period_headers: list[str]
    line_items: list[LineItem] = field(default_factory=list)


def _detect_column_lines(gray: np.ndarray, top_frac=0.03, bottom_frac=0.9, min_frac=0.45) -> list[int]:
    h, w = gray.shape
    top, bottom = int(h * top_frac), int(h * bottom_frac)
    region = gray[top:bottom, :]
    dark = (region < 150).sum(axis=0)
    thresh = (bottom - top) * min_frac
    cols = np.where(dark > thresh)[0]
    if len(cols) == 0:
        return []
    groups: list[int] = []
    cur = [cols[0]]
    for c in cols[1:]:
        if c - cur[-1] <= 6:
            cur.append(c)
        else:
            groups.append(int(np.mean(cur)))
            cur = [c]
    groups.append(int(np.mean(cur)))
    return groups


def _label_rows(img: Image.Image, x0: int, x1: int) -> list[tuple[int, str]]:
    crop = img.crop((x0, 0, x1, img.height))
    data = pytesseract.image_to_data(crop, config="--psm 4", output_type=pytesseract.Output.DICT)
    rows: dict[int, list[tuple[int, str]]] = {}
    for i, raw in enumerate(data["text"]):
        text = raw.strip()
        if not text:
            continue
        top = data["top"][i]
        key = None
        for existing in rows:
            if abs(existing - top) < 18:
                key = existing
                break
        if key is None:
            key = top
            rows[key] = []
        rows[key].append((data["left"][i], text))
    out = []
    for top in sorted(rows.keys()):
        words = sorted(rows[top])
        out.append((top, " ".join(w[1] for w in words)))
    return out


def _split_label_schedule(text: str) -> tuple[str, str | None]:
    """'Reserves and surplus 2' -> ('Reserves and surplus', '2')."""
    m = re.match(r"^(.*\D)\s+([0-9]{1,2}[A-Za-z]?)$", text.strip())
    if m and len(m.group(1).strip()) > 2:
        return m.group(1).strip(), m.group(2)
    return text.strip(), None


def _cell_value(img: Image.Image, x0: int, x1: int, y_center: int, half_height: int) -> str | None:
    crop = img.crop((x0, max(0, y_center - half_height), x1, y_center + half_height))
    txt = pytesseract.image_to_string(
        crop, config="--psm 7 -c tessedit_char_whitelist=0123456789,.()-"
    ).strip()
    return txt or None


def _detect_period_headers(img: Image.Image, header_band_bottom: int, bands: list[tuple[int, int]]) -> list[str]:
    headers = []
    for (x0, x1) in bands[1:]:
        crop = img.crop((x0, 0, x1, header_band_bottom))
        txt = pytesseract.image_to_string(crop, config="--psm 6").strip()
        txt = " ".join(txt.split())
        headers.append(txt or f"column_{x0}")
    return headers


def extract_table(img: Image.Image) -> TableExtraction:
    """Run the full label-row + per-cell OCR pipeline on one page image."""
    gray = np.array(img.convert("L"))
    lines = _detect_column_lines(gray)
    edges = [0] + lines + [img.width]
    bands = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

    if len(bands) < 2:
        # No table grid detected at all - nothing structured to extract.
        return TableExtraction(period_headers=[], line_items=[])

    label_band = bands[0]
    value_bands = bands[1:]

    label_rows = _label_rows(img, *label_band)
    period_headers = _detect_period_headers(img, header_band_bottom=label_rows[0][0] + 40 if label_rows else 400, bands=bands)

    # Estimate typical row spacing to size the cell crop height.
    tops = [t for t, _ in label_rows]
    diffs = [b - a for a, b in zip(tops, tops[1:]) if 0 < (b - a) < 200]
    row_height = int(np.median(diffs)) if diffs else 70
    half_height = max(20, row_height // 2 + 8)

    items: list[LineItem] = []
    for top, text in label_rows:
        label, schedule = _split_label_schedule(text)
        if not label or label.isupper() and len(label) <= 3:
            continue
        values = [_cell_value(img, x0, x1, top + 15, half_height) for (x0, x1) in value_bands]
        if not label:
            continue
        items.append(LineItem(label=label, schedule=schedule, values=values, y=top))

    return TableExtraction(period_headers=period_headers, line_items=items)


def parse_number(raw: str | None) -> float | None:
    """'(1,234.50)' -> -1234.5 ; '12,928,057,065' -> 12928057065.0 ; '-' -> None."""
    if raw is None:
        return None
    raw = raw.strip()
    if raw in {"", "-", "—", "–"}:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.strip("()").replace(",", "").replace(" ", "")
    m = NUMBER_RE.search(cleaned)
    if not m:
        return None
    try:
        value = float(m.group(0))
    except ValueError:
        return None
    return -value if negative else value
