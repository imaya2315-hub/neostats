"""
AI-based field & table extraction.

Two complementary extraction paths feed the final structured output:

1. `ocr_service.PageArtifact.table` — deterministic table extraction for
   financial statements.
2. LLM extraction over native/OCR page text for document headers, summary
   fields, and invoice line items.

The LLM output is normalized and merged with deterministic table output.
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
        "invoice_number",
        "invoice_date",
        "vendor_name",
        "customer_name",
        "currency",
        "subtotal",
        "tax_amount",
        "discount",
        "total_amount",
    ],
    "balance_sheet": [
        "total_assets",
        "total_liabilities",
        "total_equity",
        "currency",
    ],
    "profit_and_loss": [
        "revenue",
        "cost_of_sales",
        "gross_profit",
        "operating_expenses",
        "operating_profit",
        "tax",
        "net_profit",
        "currency",
    ],
    "cash_flow_statement": [
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "opening_cash",
        "net_change_in_cash",
        "closing_cash",
        "currency",
    ],
}


_DOC_TYPE_GUIDANCE = {
"invoice": (
    "This is an INVOICE or RECEIPT.\n"
    "Extract the following fields when explicitly visible:\n"
    "invoice_number, invoice_date, due_date, po_number,\n"
    "vendor_name, vendor_address, customer_name, customer_address,\n"
    "currency, subtotal, discount, tax_amount,\n"
    "shipping_other_charges, total_amount, cash_paid, change.\n\n"

    "Extract every visible line item in reading order with:\n"
    "description, quantity, unit_price, amount.\n\n"

    "IMPORTANT EXTRACTION RULES:\n"
    "1. invoice_date MUST be a complete date STRING. "
    "Never return only the day number.\n"
    "2. vendor_address MUST be the complete address STRING.\n"
    "3. subtotal MUST be extracted when a subtotal/total-before-tax "
    "amount is explicitly visible.\n"
    "4. total_amount MUST be the explicitly printed invoice/receipt total.\n"
    "5. cash_paid MUST be the explicitly printed cash/payment amount.\n"
    "6. change MUST be the explicitly printed change amount.\n"
    "7. NEVER calculate change from cash_paid and total_amount.\n"
    "8. NEVER replace a printed value with a calculated value.\n"
    "9. If a value is not explicitly visible, return null.\n"
),

    "balance_sheet": (
        "This is a BALANCE SHEET. Extract header information "
        "(entity/company name, statement title, currency, reporting "
        "periods/period-end dates) and every visible summary total you "
        "can find at minimum: total_assets, total_liabilities, "
        "total_equity, total_capital_and_liabilities — for EACH "
        "period/column present, as an object mapping period label to "
        "numeric value. Also list every other summary sub-total row "
        "you can see."
    ),

    "profit_and_loss": (
        "This is a PROFIT & LOSS / INCOME statement. Extract header "
        "information and, for EACH period/column present, extract: "
        "revenue, cost_of_sales, gross_profit, operating_expenses, "
        "operating_profit, tax, net_profit. If this is a bank/financial "
        "institution statement, also extract interest_earned, "
        "other_income, total_income, interest_expended, "
        "provisions_and_contingencies, total_expenditure, "
        "net_profit_before_minority_interest, minority_interest, "
        "net_profit_after_minority_interest, brought_forward_profit, "
        "total_available_for_appropriation."
    ),

    "cash_flow_statement": (
        "This is a CASH FLOW STATEMENT. Extract header information "
        "and, for EACH period/column present, extract: "
        "operating_cash_flow, investing_cash_flow, financing_cash_flow, "
        "fx_translation_adjustment, net_change_in_cash, opening_cash, "
        "cash_acquired_on_amalgamation, closing_cash."
    ),
}


_SYSTEM_PROMPT = (
    "You are a highly precise financial-document data-extraction engine. "
    "You receive OCR/native text split into pages using [PAGE n] markers. "
    "Return ONLY one valid JSON object. Never return prose or markdown.\n\n"

    "GENERAL RULES:\n"
    "1. Extract every meaningful field that is explicitly visible.\n"
    "2. NEVER invent, guess, calculate, or infer a value that is not explicitly "
    "present in the supplied document text.\n"
    "3. If a field is missing or genuinely unreadable, return null.\n"
    "4. Every extracted field must contain source_text with the exact short "
    "OCR/native-text snippet used for the value.\n"
    "5. source_text must never be fabricated.\n"
    "6. page_number must identify the page containing the source text.\n"
    "7. Numbers must be plain JSON numbers without currency symbols or commas.\n"
    "8. Negative values explicitly shown with parentheses/brackets should be "
    "represented as negative numbers.\n\n"

    "DATE RULES:\n"
    "9. Dates are STRINGS, never numbers.\n"
    "10. Always extract the COMPLETE visible date.\n"
    "11. For example, if the text contains '04 Jan 2017 01:15pm', "
    "the value must be '04 Jan 2017' or '2017-01-04', never simply 4.\n"
    "12. Do not convert the day portion of a date into a numeric field.\n\n"

    "ADDRESS RULES:\n"
    "13. Addresses are STRINGS.\n"
    "14. Extract the complete visible address, not merely the first number "
    "or postal code.\n\n"

    "PAYMENT RULES:\n"
    "15. Extract total_amount from the explicitly printed total.\n"
    "16. Extract cash_paid from the explicitly printed payment/cash amount.\n"
    "17. Extract change from the explicitly printed change amount.\n"
    "18. NEVER calculate change yourself.\n"
    "19. NEVER calculate total_amount yourself.\n"
    "20. NEVER use cash_paid as total_amount or change as cash_paid.\n"
    "21. If the OCR text is ambiguous, return null rather than guessing.\n\n"

    "LINE ITEM RULES:\n"
    "22. Extract every visible line item in reading order.\n"
    "23. If quantity, unit_price, or amount is explicitly printed, extract it.\n"
    "24. Do not calculate an amount when the printed amount is available.\n"
    "25. If an individual line-item value is not visible, use null.\n\n"

    "OUTPUT SHAPE:\n"
    "{\n"
    '  "fields": {\n'
    '    "<field_name>": {\n'
    '      "value": <string|number|object|null>,\n'
    '      "source_text": "<exact snippet or null>",\n'
    '      "page_number": <int|null>\n'
    "    }\n"
    "  },\n"
    '  "line_items": [\n'
    "    {\n"
    '      "description": "<string|null>",\n'
    '      "quantity": <number|null>,\n'
    '      "unit_price": <number|null>,\n'
    '      "amount": <number|null>,\n'
    '      "page_number": <int|null>\n'
    "    }\n"
    "  ],\n"
    '  "statement_line_items": [],\n'
    '  "period_headers": []\n'
    "}\n\n"

    "`line_items` is used for invoices.\n"
    "`statement_line_items` and `period_headers` are used for financial statements."
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

    body = "\n\n".join(
        f"[PAGE {i}]\n{text}"
        for i, text in enumerate(page_texts, start=1)
    )

    return (
        f"{guidance}\n\n"
        f"Minimum required field names "
        f"(include them even if null): {', '.join(required)}.\n\n"
        "DOCUMENT TEXT:\n"
        f"{body}"
    )


def _call_llm(document_type: str, page_texts: list[str]) -> dict:
    settings = get_settings()

    if not settings.GROQ_API_KEY:
        raise ExtractionError(
            "LLM_NOT_CONFIGURED: GROQ_API_KEY is not set; "
            "field extraction cannot run."
        )

    try:
        from groq import Groq
    except ImportError as exc:
        raise ExtractionError(
            f"Groq SDK not installed: {exc}"
        ) from exc

    client = Groq(
        api_key=settings.GROQ_API_KEY,
        timeout=settings.LLM_TIMEOUT_SECONDS,
    )

    user_prompt = _build_user_prompt(
        document_type,
        page_texts,
    )

    try:
        response = client.chat.completions.create(
            model=settings.GROQ_MODEL,

            # Groq currently limits your output to 1000 TPM.
            # Keep a safety margin below that limit.
            max_tokens=900,

            response_format={
                "type": "json_object"
            },

            messages=[
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
        )

    except Exception as exc:
        logger.exception(
            "LLM call failed for document_type=%s",
            document_type,
        )

        raise ExtractionError(
            f"LLM_CALL_FAILED: {exc}"
        ) from exc

    raw_text = (
        response.choices[0]
        .message
        .content
        or ""
    )

    return _parse_llm_json(raw_text)


def _parse_llm_json(raw_text: str) -> dict:
    cleaned = raw_text.strip()

    cleaned = re.sub(
        r"^```(?:json)?",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()

    cleaned = re.sub(
        r"```$",
        "",
        cleaned,
    ).strip()

    try:
        return json.loads(cleaned)

    except json.JSONDecodeError:
        match = re.search(
            r"\{.*\}",
            cleaned,
            flags=re.DOTALL,
        )

        if match:
            return json.loads(match.group(0))

        raise ExtractionError(
            "LLM_RESPONSE_NOT_JSON: could not parse model output as JSON"
        )


def _locate_page(
    source_text: str | None,
    page_texts: list[str],
) -> int | None:
    if not source_text:
        return None

    needle = source_text.strip().lower()

    if not needle:
        return None

    for i, text in enumerate(page_texts, start=1):
        if needle in text.lower():
            return i

    return None


# Fields that must remain strings even if they contain numbers.
_STRING_FIELDS = {
    "invoice_date",
    "due_date",
    "vendor_name",
    "vendor_address",
    "customer_name",
    "customer_address",
    "currency",
    "payment_terms",
    "invoice_number",
    "po_number",
    "notes",
    "gst_registration_number",
    "phone_number",
    "served_by",
    "reference_number",
}


def _normalize_field_value(field_name: str, value):
    """
    Normalize numeric fields while preserving semantic string fields.

    Dates, addresses, identifiers and names must never be converted to
    numbers merely because the OCR contains digits.
    """

    if value is None:
        return None

    if field_name in _STRING_FIELDS:
        if isinstance(value, str):
            return value.strip()

        # Preserve identifiers as strings if the model accidentally returns
        # a numeric JSON value.
        if isinstance(value, (int, float)):
            return str(value)

        return value

    return _normalize_numeric(value)


def _normalize_numeric(value):
    if isinstance(value, (int, float)) or value is None:
        return value

    if isinstance(value, str):
        parsed = parse_number(value)
        return parsed if parsed is not None else value

    if isinstance(value, dict):
        return {
            k: _normalize_numeric(v)
            for k, v in value.items()
        }

    return value


def _table_to_statement_items(
    table,
    page_number: int,
) -> list[dict]:
    items = []

    for line in table.line_items:
        values = {}

        for header, raw_val in zip(
            table.period_headers,
            line.values,
        ):
            values[header or f"column_{len(values)}"] = parse_number(
                raw_val
            )

        items.append(
            {
                "label": line.label,
                "schedule": line.schedule,
                "values": values,
                "page_number": page_number,
            }
        )

    return items
def _recover_invoice_subtotal(
    fields: dict,
    line_items: list[dict],
    warnings: list[str],
) -> None:
    """
    Recover/repair subtotal using line-item amounts.

    Rules:
    1. If subtotal is missing, derive it from line items.
    2. If subtotal exists but is clearly inconsistent with the
       line-item sum, replace it with the line-item sum.
    3. Never use an unrelated OCR number as the subtotal.
    """

    if not line_items:
        return

    amounts = []

    for item in line_items:
        amount = item.get("amount")

        if isinstance(amount, (int, float)):
            amounts.append(float(amount))

    if not amounts:
        return

    line_item_total = round(
        sum(amounts),
        2,
    )

    subtotal_field = fields.get("subtotal")

    current_subtotal = None

    if isinstance(subtotal_field, dict):
        value = subtotal_field.get("value")

        if isinstance(value, (int, float)):
            current_subtotal = float(value)

    if current_subtotal is None:
        fields["subtotal"] = {
            "value": line_item_total,
            "source_text": (
                "Derived from the sum of extracted line-item amounts"
            ),
            "page_number": None,
        }

        warnings.append(
            "Subtotal was missing; recovered from line-item amounts."
        )

        return

    if abs(current_subtotal - line_item_total) > 0.05:
        fields["subtotal"] = {
            "value": line_item_total,
            "source_text": (
                "Derived from the sum of extracted line-item amounts "
                f"(original extracted subtotal: {current_subtotal})"
            ),
            "page_number": None,
        }

        warnings.append(
            "Extracted subtotal was inconsistent with line items; "
            "recovered subtotal from line-item amounts."
        )

def _validate_extracted_payment_fields(
    fields: dict,
    warnings: list[str],
) -> None:
    cash_paid_field = fields.get("cash_paid")
    total_amount_field = fields.get("total_amount")
    change_field = fields.get("change")

    cash_paid = (
        cash_paid_field.get("value")
        if isinstance(cash_paid_field, dict)
        else None
    )

    total_amount = (
        total_amount_field.get("value")
        if isinstance(total_amount_field, dict)
        else None
    )

    change = (
        change_field.get("value")
        if isinstance(change_field, dict)
        else None
    )

    if (
        isinstance(cash_paid, (int, float))
        and isinstance(total_amount, (int, float))
    ):
        expected_change = round(
            cash_paid - total_amount,
            2,
        )

        if expected_change >= 0:

            if not isinstance(change, (int, float)):
                fields["change"] = {
                    "value": expected_change,
                    "source_text": (
                        "Derived from cash paid minus total amount"
                    ),
                    "page_number": None,
                }

                warnings.append(
                    "Change was missing; derived from "
                    "cash_paid - total_amount."
                )

            elif abs(change - expected_change) > 0.05:
                original_change = change

                fields["change"] = {
                    "value": expected_change,
                    "source_text": (
                        "Derived from cash paid minus total amount"
                    ),
                    "page_number": None,
                }

                warnings.append(
                    "Extracted change was inconsistent with "
                    f"cash_paid - total_amount; replaced "
                    f"{original_change} with {expected_change}."
                )
def extract(
    document_type: str,
    artifacts: list[PageArtifact],
) -> ExtractionOutcome:

    warnings: list[str] = []

    page_texts = [
        a.text
        for a in artifacts
    ]

    llm_json = _call_llm(
        document_type,
        page_texts,
    )

    fields = llm_json.get(
        "fields",
        {},
    ) or {}

    for name, field in fields.items():

        if not isinstance(field, dict):
            fields[name] = {
                "value": _normalize_field_value(
                    name,
                    field,
                ),
                "source_text": None,
                "page_number": None,
            }
            continue

        field["value"] = _normalize_field_value(
            name,
            field.get("value"),
        )

        if field.get("page_number") is None:
            field["page_number"] = _locate_page(
                field.get("source_text"),
                page_texts,
            )

    line_items = llm_json.get(
        "line_items",
        [],
    ) or []

    for item in line_items:
        for key in (
            "quantity",
            "unit_price",
            "amount",
        ):
            if key in item:
                item[key] = _normalize_numeric(
                    item[key]
                )

    if document_type == "invoice":
        _recover_invoice_subtotal(
            fields,
            line_items,
            warnings,
        )

        _validate_extracted_payment_fields(
            fields,
            warnings,
        )

    statement_line_items: list[dict] = []

    period_headers: list[str] = (
        llm_json.get(
            "period_headers",
            [],
        )
        or []
    )

    used_deterministic_table = False

    for i, artifact in enumerate(
        artifacts,
        start=1,
    ):

        if artifact.table and artifact.table.line_items:

            statement_line_items.extend(
                _table_to_statement_items(
                    artifact.table,
                    i,
                )
            )

            if artifact.table.period_headers:
                period_headers = (
                    artifact.table.period_headers
                )

            used_deterministic_table = True

    if not used_deterministic_table:

        statement_line_items = (
            llm_json.get(
                "statement_line_items",
                [],
            )
            or []
        )

        for item in statement_line_items:
            item["values"] = _normalize_numeric(
                item.get("values", {})
            )

        if (
            document_type != "invoice"
            and not statement_line_items
        ):
            warnings.append(
                "No statement line items were detected "
                "either via table-grid OCR or the LLM pass."
            )

    data = {
        "fields": fields,
        "line_items": line_items,
        "statement_line_items": statement_line_items,
        "period_headers": period_headers,
    }

    settings = get_settings()

    return ExtractionOutcome(
        data=data,
        llm_model=settings.GROQ_MODEL,
        warnings=warnings,
    )
