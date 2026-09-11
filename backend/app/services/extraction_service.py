"""
AI-based field & table extraction.

Two complementary extraction paths feed the final structured output:

1. `ocr_service.PageArtifact.table` — a deterministic, non-LLM table
   extraction (vertical-line detection + per-cell OCR) already produced
   for financial-statement pages by `table_ocr.py`. This is the most
   reliable source for statement line items/values because it never
   hallucinates: every cell is grounded in a specific pixel region.
2. An LLM pass over the page text (native or OCR'd) that extracts header
   / summary fields (parties, dates, currency, totals) for every document
   type, and full line items for invoices (which have no pre-built table
   extraction, since `expects_table=False` for invoices upstream).

The two are merged: LLM output supplies `fields` (+ invoice line items),
the deterministic table extractor supplies `statement_line_items` for
financial statements whenever it found a grid. If the grid detector found
nothing, we fall back to asking the LLM for statement line items too.

Missing values are always returned as null; the model is instructed never
to invent a value that is not visibly present in the supplied text.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.ocr_service import PageArtifact
from app.utils.table_ocr import parse_number

logger = get_logger("docintel.extraction")

REQUIRED_FIELDS = {
    "invoice": [
        "invoice_number", "invoice_date", "vendor_name", "customer_name",
        "currency", "subtotal", "tax_amount", "discount", "total_amount",
    ],
    "balance_sheet": ["total_assets", "total_liabilities", "total_equity", "currency"],
    "profit_and_loss": [
        "revenue", "cost_of_sales", "gross_profit", "operating_expenses",
        "operating_profit", "tax", "net_profit", "currency",
    ],
    "cash_flow_statement": [
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
        "opening_cash", "net_change_in_cash", "closing_cash", "currency",
    ],
    "cash_flow": [
        "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
        "opening_cash", "net_change_in_cash", "closing_cash", "currency",
    ],
}

BANK_PNL_REQUIRED_FIELDS = [
    "interest_earned", "other_income", "total_income", "interest_expended",
    "operating_expenses", "provisions_and_contingencies", "total_expenditure",
    "net_profit_before_minority_interest", "net_profit_after_minority_interest",
    "currency",
]


def get_required_fields(document_type: str, fields: dict | None = None) -> list[str]:
    f = fields or {}
    if document_type == "profit_and_loss":
        bank_names = ["interest_earned", "total_income", "total_expenditure", "interest_expended"]
        if any((f.get(n) or {}).get("value") is not None for n in bank_names):
            return BANK_PNL_REQUIRED_FIELDS
    return REQUIRED_FIELDS.get(document_type, [])


_DOC_TYPE_GUIDANCE = {
    "invoice": (
        "This is an INVOICE or RECEIPT. Extract all visible fields:\n"
        "- invoice_number, invoice_date, due_date, vendor_name, vendor_address, customer_name, customer_address, currency\n"
        "- subtotal: the sum of line items before taxes/discounts, or net amount\n"
        "- tax_amount: the tax or GST/VAT amount (if 0 or zero-rated, report 0)\n"
        "- tax_rate: percentage if stated (e.g. '6%')\n"
        "- tax_inclusive: true if prices/total already include tax (e.g. 'GST included', 'tax inclusive'), false otherwise\n"
        "- discount: any discount amount\n"
        "- total_amount: the final payable grand total\n"
        "- cash_paid: cash or tender amount tendered by customer (e.g. 'Cash', 'Paid')\n"
        "- change: change given back to customer (e.g. 'Change', 'Return')\n"
        "- line_items: list of line items with description, quantity (null if not explicitly visible - NEVER infer or invent quantity), unit_price (null if not explicitly visible), amount."
    ),
    "balance_sheet": (
        "This is a BALANCE SHEET. Extract header info (entity name, reporting periods in `period_headers`).\n"
        "For EACH period/column present, map numeric values as an object: {\"value\": {\"<period>\": <number>}} for:\n"
        "total_assets, total_liabilities, total_equity, total_capital_and_liabilities, current_assets, non_current_assets, current_liabilities.\n"
        "Also list all rows in `statement_line_items` with label, schedule, values."
    ),
    "profit_and_loss": (
        "This is a PROFIT & LOSS / INCOME statement (Corporate or Bank/Financial Institution).\n"
        "1. Identify the comparative periods/years in the column headers (e.g. '2026', '2025' or 'March 31, 2026', 'March 31, 2025') and put them in `period_headers`.\n"
        "2. For EVERY financial amount, provide an object mapping each period column to its numeric value in `fields`:\n"
        "   If Bank P&L: interest_earned, other_income, total_income, interest_expended, operating_expenses, provisions_and_contingencies, total_expenditure, net_profit_before_minority_interest, minority_interest, net_profit_after_minority_interest, brought_forward_profit, total_available_for_appropriation.\n"
        "   If Corporate P&L: revenue, cost_of_sales, gross_profit, operating_expenses, operating_profit, tax, net_profit.\n"
        "   Format: {\"value\": {\"2026\": 348615.15, \"2025\": 336367.43}, \"source_text\": \"...\", \"page_number\": 1}\n"
        "3. In `statement_line_items`, list each row: {\"label\": \"...\", \"schedule\": \"...\", \"values\": {\"<period>\": <num>}, \"page_number\": 1}.\n"
        "4. Do NOT extract dates as numeric financial values (do not extract 312026 from March 31, 2026)."
    ),
    "cash_flow_statement": (
        "This is a CASH FLOW STATEMENT. Identify comparative periods in `period_headers`.\n"
        "For EACH period, map: operating_cash_flow, investing_cash_flow, financing_cash_flow, fx_translation_adjustment, net_change_in_cash, opening_cash, cash_acquired_on_amalgamation, closing_cash as {\"value\": {\"<period>\": <number>}}.\n"
        "Also list all rows in `statement_line_items` with label, schedule, values."
    ),
}
_DOC_TYPE_GUIDANCE["cash_flow"] = _DOC_TYPE_GUIDANCE["cash_flow_statement"]

_SYSTEM_PROMPT = (
    "You are a precise financial-document data-extraction engine. You are given "
    "the OCR/native text of a document, split into pages with [PAGE n] markers. "
    "Return ONLY a single JSON object, no prose, no markdown fences.\n"
    "Rules:\n"
    "1. Extract EVERY meaningful field visible in the text, not only the fields "
    "named in the guidance below — the guidance lists a minimum, not a ceiling.\n"
    "2. NEVER invent, guess, or infer a value that is not explicitly present in "
    "the text. If a field is not present, set its value to null.\n"
    "3. For every field, include the exact short snippet of source text you read "
    "the value from (`source_text`), so it can be traced back to the document.\n"
    "4. Numbers must be plain numbers (no currency symbols/commas) in JSON; use "
    "negative numbers for amounts shown in parentheses.\n"
    "5. For multi-period financial statements (current year and previous year), "
    "store values as an object mapping period header to number: {\"value\": {\"<period>\": <num>}}.\n"
    "6. Output must match this JSON shape exactly:\n"
    "{\n"
    '  "fields": {\n'
    '    "<field_name>": {"value": <string|number|object|null>, "source_text": "<snippet or null>", "page_number": <int or null>}\n'
    "  },\n"
    '  "line_items": [ {"description": "...", "quantity": <num|null>, "unit_price": <num|null>, "amount": <num|null>, "page_number": <int|null>} ],\n'
    '  "statement_line_items": [ {"label": "...", "schedule": "<string|null>", "values": {"<period>": <num|null>}, "page_number": <int|null>} ],\n'
    '  "period_headers": ["<period label>", ...]\n'
    "}\n"
    "`line_items` is only used for invoices. `statement_line_items` and "
    "`period_headers` are only used for financial statements."
)


class ExtractionError(RuntimeError):
    """Raised when the LLM extraction step cannot be completed."""


@dataclass
class ExtractionOutcome:
    data: dict
    llm_model: str | None
    warnings: list[str]


def _build_user_prompt(document_type: str, page_texts: list[str]) -> str:
    guidance = _DOC_TYPE_GUIDANCE.get(document_type, "")
    required = REQUIRED_FIELDS.get(document_type, [])
    body = "\n\n".join(f"[PAGE {i}]\n{text}" for i, text in enumerate(page_texts, start=1))
    return (
        f"{guidance}\n\nMinimum required field names (include them even if null): "
        f"{', '.join(required)}.\n\nDOCUMENT TEXT:\n{body}"
    )


def _call_llm(document_type: str, page_texts: list[str]) -> dict:
    settings = get_settings()
    if not settings.GROQ_API_KEY:
        raise ExtractionError(
            "LLM_NOT_CONFIGURED: GROQ_API_KEY is not set; field extraction cannot run."
        )

    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover - dependency issue
        raise ExtractionError(f"Groq SDK not installed: {exc}") from exc

    client = Groq(api_key=settings.GROQ_API_KEY, timeout=settings.LLM_TIMEOUT_SECONDS)
    user_prompt = _build_user_prompt(document_type, page_texts)

    response = None
    last_exc = None
    for attempt in range(4):
        try:
            response = client.chat.completions.create(
                model=settings.GROQ_MODEL,
                max_tokens=settings.LLM_MAX_TOKENS,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            err_msg = str(exc).lower()
            if ("rate_limit" in err_msg or "429" in err_msg or "service unavailable" in err_msg or "503" in err_msg) and attempt < 3:
                wait_sec = (attempt + 1) * 3
                logger.warning("LLM API transient error (%s). Retrying in %ss (attempt %d/3)...", exc, wait_sec, attempt + 1)
                time.sleep(wait_sec)
                continue
            logger.exception("LLM call failed for document_type=%s", document_type)
            raise ExtractionError(f"LLM_CALL_FAILED: {exc}") from exc

    if response is None:
        raise ExtractionError(f"LLM_CALL_FAILED: {last_exc}")

    raw_text = response.choices[0].message.content or ""
    return _parse_llm_json(raw_text)

def _parse_llm_json(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Try to salvage a JSON object embedded in extra prose.
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ExtractionError("LLM_RESPONSE_NOT_JSON: could not parse model output as JSON")


def _locate_page(source_text: str | None, page_texts: list[str]) -> int | None:
    if not source_text:
        return None
    needle = source_text.strip().lower()
    if not needle:
        return None
    for i, text in enumerate(page_texts, start=1):
        if needle in text.lower():
            return i
    return None


def _normalize_numeric(value):
    if isinstance(value, (int, float)) or value is None:
        return value
    if isinstance(value, str):
        parsed = parse_number(value)
        return parsed if parsed is not None else value
    if isinstance(value, dict):
        return {k: _normalize_numeric(v) for k, v in value.items()}
    return value


def _table_to_statement_items(table, page_number: int) -> list[dict]:
    items = []
    for line in table.line_items:
        values = {}
        for header, raw_val in zip(table.period_headers, line.values):
            values[header or f"column_{len(values)}"] = parse_number(raw_val)
        items.append(
            {
                "label": line.label,
                "schedule": line.schedule,
                "values": values,
                "page_number": page_number,
            }
        )
    return items


def extract(document_type: str, artifacts: list[PageArtifact]) -> ExtractionOutcome:
    warnings: list[str] = []
    page_texts = [a.text for a in artifacts]

    llm_json = _call_llm(document_type, page_texts)

    fields = llm_json.get("fields", {}) or {}
    for name, field in fields.items():
        if not isinstance(field, dict):
            fields[name] = {"value": field, "source_text": None, "page_number": None}
            continue
        field["value"] = _normalize_numeric(field.get("value"))
        if field.get("page_number") is None:
            field["page_number"] = _locate_page(field.get("source_text"), page_texts)

    # Re-collapse flattened period keys (e.g. interest_earned_current / interest_earned_previous)
    collapsed_fields: dict[str, dict] = {}
    flattened_pattern = re.compile(r"^(.*)_(current|previous|prior|20\d\d)$", re.IGNORECASE)
    for name, field in list(fields.items()):
        m = flattened_pattern.match(name)
        if m:
            base_name, period_tag = m.group(1), m.group(2)
            if base_name not in collapsed_fields:
                collapsed_fields[base_name] = {
                    "value": {},
                    "source_text": field.get("source_text"),
                    "page_number": field.get("page_number"),
                }
            collapsed_fields[base_name]["value"][period_tag] = field.get("value")

    for base_name, c_field in collapsed_fields.items():
        if base_name not in fields or fields[base_name].get("value") is None:
            fields[base_name] = c_field

    # Sanitize reporting period if extracted as a merged numeric date like 312026
    for p_key in ("period", "reporting_period", "year"):
        if p_key in fields:
            p_val = fields[p_key].get("value")
            if isinstance(p_val, (int, float)) and p_val > 100000:
                fields[p_key]["value"] = fields[p_key].get("source_text") or str(int(p_val))

    line_items = llm_json.get("line_items", []) or []
    for item in line_items:
        for key in ("quantity", "unit_price", "amount"):
            if key in item:
                item[key] = _normalize_numeric(item[key])

    # Prefer the deterministic, grid-based table extraction for financial
    # statements whenever it actually found a table on some page.
    statement_line_items: list[dict] = []
    period_headers: list[str] = llm_json.get("period_headers", []) or []
    used_deterministic_table = False
    for i, artifact in enumerate(artifacts, start=1):
        if artifact.table and artifact.table.line_items:
            statement_line_items.extend(_table_to_statement_items(artifact.table, i))
            if artifact.table.period_headers:
                period_headers = artifact.table.period_headers
            used_deterministic_table = True

    if not used_deterministic_table:
        statement_line_items = llm_json.get("statement_line_items", []) or []
        for item in statement_line_items:
            item["values"] = _normalize_numeric(item.get("values", {}))
        if document_type != "invoice" and not statement_line_items:
            warnings.append(
                "No statement line items were detected either via table-grid OCR or the LLM pass."
            )

    data = {
        "fields": fields,
        "line_items": line_items,
        "statement_line_items": statement_line_items,
        "period_headers": period_headers,
    }

    settings = get_settings()
    return ExtractionOutcome(data=data, llm_model=settings.GROQ_MODEL, warnings=warnings)