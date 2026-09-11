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
}

_DOC_TYPE_GUIDANCE = {
    "invoice": (
        "This is an INVOICE. Extract every visible header field (invoice number, "
        "invoice date, due date, PO number, vendor name & address, customer name & "
        "address, currency, payment terms, subtotal, discount, tax amount, "
        "shipping/other charges, total_amount, cash_paid, change, notes) and the "
        "full line-item table (description, quantity, unit_price, amount) for "
        "every row visible, in reading order."
    ),
    "balance_sheet": (
        "This is a BALANCE SHEET. Extract header information (entity/company name, "
        "statement title, currency, reporting periods/period-end dates) and every "
        "visible summary total you can find at minimum: total_assets, "
        "total_liabilities, total_equity, total_capital_and_liabilities — for EACH "
        "period/column present, as an object mapping period label to numeric value. "
        "Also list every other summary sub-total row you can see (e.g. current "
        "assets, non-current assets, current liabilities) the same way."
    ),
    "profit_and_loss": (
        "This is a PROFIT & LOSS / INCOME statement. Extract header information "
        "(entity name, statement title, currency, reporting periods) and, for EACH "
        "period/column present, as an object mapping period label to numeric value: "
        "revenue, cost_of_sales (COGS), gross_profit, operating_expenses, "
        "operating_profit, tax, net_profit, and — if this is a bank/financial "
        "institution statement instead — interest_earned, other_income, "
        "total_income, interest_expended, provisions_and_contingencies, "
        "total_expenditure, net_profit_before_minority_interest, minority_interest, "
        "net_profit_after_minority_interest, brought_forward_profit, "
        "total_available_for_appropriation."
    ),
    "cash_flow_statement": (
        "This is a CASH FLOW STATEMENT. Extract header information (entity name, "
        "statement title, currency, reporting periods) and, for EACH period/column "
        "present, as an object mapping period label to numeric value: "
        "operating_cash_flow, investing_cash_flow, financing_cash_flow, "
        "fx_translation_adjustment, net_change_in_cash, opening_cash, "
        "cash_acquired_on_amalgamation, closing_cash."
    ),
}

_SYSTEM_PROMPT = (
    "You are a precise financial-document data-extraction engine. You are given "
    "the OCR/native text of a document, split into pages with [PAGE n] markers. "
    "Return ONLY a single JSON object, no prose, no markdown fences. "
    "Rules:\n"
    "1. Extract EVERY meaningful field visible in the text, not only the fields "
    "named in the guidance below — the guidance lists a minimum, not a ceiling.\n"
    "2. NEVER invent, guess, or infer a value that is not explicitly present in "
    "the text. If a field is not present, set its value to null.\n"
    "3. For every field, include the exact short snippet of source text you read "
    "the value from (`source_text`), so it can be traced back to the document.\n"
    "4. Numbers must be plain numbers (no currency symbols/commas) in JSON; use "
    "negative numbers for amounts shown in parentheses.\n"
    "5. Output must match this JSON shape exactly:\n"
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
    except Exception as exc:  # noqa: BLE001 - normalize all provider failures
        logger.exception("LLM call failed for document_type=%s", document_type)
        raise ExtractionError(f"LLM_CALL_FAILED: {exc}") from exc

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