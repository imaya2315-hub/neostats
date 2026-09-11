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

try:
    import pytesseract
except ImportError:
    pytesseract = None
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
    if pytesseract is None:
        return []
    crop = img.crop((x0, 0, x1, img.height))
    try:
        data = pytesseract.image_to_data(crop, config="--psm 4", output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    rows: dict[int, list[tuple[int, str]]] = {}
    for i, raw in enumerate(data.get("text", [])):
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
    if pytesseract is None:
        return None
    crop = img.crop((x0, max(0, y_center - half_height), x1, y_center + half_height))
    try:
        txt = pytesseract.image_to_string(
            crop, config="--psm 7 -c tessedit_char_whitelist=0123456789,.()-"
        ).strip()
        return txt or None
    except Exception:
        return None


def _detect_period_headers(img: Image.Image, header_band_bottom: int, bands: list[tuple[int, int]]) -> list[str]:
    if pytesseract is None:
        return []
    headers = []
    for (x0, x1) in bands[1:]:
        crop = img.crop((x0, 0, x1, header_band_bottom))
        try:
            txt = pytesseract.image_to_string(crop, config="--psm 6").strip()
            txt = " ".join(txt.split())
            headers.append(txt or f"column_{x0}")
        except Exception:
            headers.append(f"column_{x0}")
    return headers


def _extract_table_spatial(img: Image.Image) -> TableExtraction | None:
    """Extract table line items from unruled financial statements using OCR bounding boxes."""
    try:
        from rapidocr_onnxruntime import RapidOCR
        # Convert PIL Image to RGB numpy array
        if img.mode != "RGB":
            img_rgb = img.convert("RGB")
        else:
            img_rgb = img
        ocr = RapidOCR()
        res, _ = ocr(np.array(img_rgb))
        if not res:
            return None

        # Build box records: (mid_y, min_x, max_x, text)
        boxes = []
        for box, text, score in res:
            text = text.strip()
            if not text:
                continue
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            boxes.append(((min(ys) + max(ys)) / 2.0, min(xs), max(xs), text))

        boxes.sort(key=lambda b: b[0])
        # Cluster boxes into lines
        rows: list[dict] = []
        for mid_y, min_x, max_x, text in boxes:
            placed = False
            for r in rows:
                if abs(r["y"] - mid_y) < 14:
                    r["items"].append((min_x, max_x, text))
                    r["y"] = (r["y"] * len(r["items"]) + mid_y) / (len(r["items"]) + 1)
                    placed = True
                    break
            if not placed:
                rows.append({"y": mid_y, "items": [(min_x, max_x, text)]})

        # Detect period headers from top rows (e.g. 2026, 2025)
        period_headers: list[str] = []
        header_y = 0.0
        for r in rows[:15]:
            texts = [item[2] for item in r["items"]]
            line_str = " ".join(texts)
            years = re.findall(r"\b(20\d\d)\b", line_str)
            if len(years) >= 2:
                # Deduplicate while preserving order
                seen = set()
                dedup_years = []
                for y in years:
                    if y not in seen:
                        seen.add(y)
                        dedup_years.append(y)
                if len(dedup_years) >= 2:
                    period_headers = dedup_years
                    header_y = r["y"]
                    break

        if not period_headers:
            return None

        # Extract statement items below header
        items: list[LineItem] = []
        for r in rows:
            if r["y"] <= header_y + 10:
                continue
            r_items = sorted(r["items"], key=lambda item: item[0])
            if not r_items:
                continue

            # Identify numeric items and label items
            label_parts: list[str] = []
            num_values: list[str] = []
            for min_x, max_x, text in r_items:
                if parse_number(text) is not None:
                    num_values.append(text)
                else:
                    label_parts.append(text)

            if not label_parts or not num_values:
                continue

            full_label = " ".join(label_parts).strip()
            # Filter out headers or short noise
            if len(full_label) < 3 or full_label.upper() in {"TOTAL", "SCHEDULE"}:
                pass
            label, schedule = _split_label_schedule(full_label)
            # Match number values to period headers
            # If we have 2 headers and 2 numbers, map 1-to-1
            vals = [None] * len(period_headers)
            for idx, val in enumerate(num_values[-len(period_headers):]):
                vals[idx] = val

            items.append(LineItem(label=label, schedule=schedule, values=vals, y=int(r["y"])))

        if items:
            return TableExtraction(period_headers=period_headers, line_items=items)
    except Exception:
        pass
    return None


def extract_table(img: Image.Image) -> TableExtraction:
    """Run table extraction using spatial OCR clustering or vertical line detection."""
    # First, try spatial OCR extraction for ruled/unruled tables
    spatial_result = _extract_table_spatial(img)
    if spatial_result and spatial_result.line_items:
        return spatial_result

    # Fallback to vertical border line detection if pytesseract is available
    if pytesseract is not None:
        try:
            gray = np.array(img.convert("L"))
            lines = _detect_column_lines(gray)
            edges = [0] + lines + [img.width]
            bands = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1)]

            if len(bands) >= 2:
                label_band = bands[0]
                value_bands = bands[1:]
                label_rows = _label_rows(img, *label_band)
                period_headers = _detect_period_headers(
                    img, header_band_bottom=label_rows[0][0] + 40 if label_rows else 400, bands=bands
                )
                tops = [t for t, _ in label_rows]
                diffs = [b - a for a, b in zip(tops, tops[1:]) if 0 < (b - a) < 200]
                row_height = int(np.median(diffs)) if diffs else 70
                half_height = max(20, row_height // 2 + 8)

                items: list[LineItem] = []
                for top, text in label_rows:
                    label, schedule = _split_label_schedule(text)
                    if not label or (label.isupper() and len(label) <= 3):
                        continue
                    values = [_cell_value(img, x0, x1, top + 15, half_height) for (x0, x1) in value_bands]
                    if not label:
                        continue
                    items.append(LineItem(label=label, schedule=schedule, values=values, y=top))

                return TableExtraction(period_headers=period_headers, line_items=items)
        except Exception:
            pass

    return TableExtraction(period_headers=[], line_items=[])


def parse_number(raw: str | None) -> float | None:
    """Robustly parse formatted numbers while rejecting dates and text.
    '(1,234.50)' -> -1234.5 ; '12,928,057,065' -> 12928057065.0 ; 'March 31, 2026' -> None ; '-' -> None.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    raw_str = str(raw).strip()
    if raw_str in {"", "-", "—", "–", "N/A", "NA", "null", "None"}:
        return None

    # Filter out text with words 3+ letters long (e.g. "March", "year", "ended", "period")
    cleaned_label = re.sub(r"[$£€₹]|(?:Rs\.?|RM|INR|USD|SGD|EUR|GBP)\b", "", raw_str, flags=re.IGNORECASE).strip()
    if re.search(r"[a-zA-Z]{3,}", cleaned_label):
        return None

    # Check for parenthesized negative: (1,234.50) or ( 1,234.50 )
    negative = False
    m_paren = re.match(r"^\s*\(\s*([^()]+)\s*\)\s*$", cleaned_label)
    if m_paren:
        negative = True
        cleaned_label = m_paren.group(1).strip()
    elif cleaned_label.startswith("-"):
        negative = True
        cleaned_label = cleaned_label.lstrip("-").strip()

    # Clean commas and spaces
    cleaned = cleaned_label.replace(",", "").replace(" ", "")
    # Must strictly match numeric format: e.g. 1234.56, 1234, .56
    if not re.match(r"^\d+(?:\.\d+)?$|^\.\d+$", cleaned):
        return None
    try:
        val = float(cleaned)
        return -val if negative else val
    except ValueError:
        return None
