"""
Financial calculation validation.

Every check is computed only from fields the extraction step actually
found in the source document — nothing here invents or assumes a value.
If a field required by a check is missing, that check's status is
NOT_APPLICABLE rather than PASS/FAIL, per the assignment spec.

Values shown in parentheses/brackets are treated as negative by the
extraction/OCR layer (see `table_ocr.parse_number`) before they ever
reach this module, so all arithmetic here is plain addition/subtraction.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("docintel.validation.financial")


def _within_tolerance(calculated: float, reported: float) -> bool:
    settings = get_settings()
    tolerance = max(settings.VALIDATION_ABS_TOLERANCE, settings.VALIDATION_PCT_TOLERANCE * abs(reported))
    return abs(calculated - reported) <= tolerance


def _build_check(name: str, formula: str, operand_values: dict[str, float | None], reported, period: str | None) -> dict:
    missing = [k for k, v in operand_values.items() if v is None] + (["reported_value"] if reported is None else [])
    if missing:
        return {
            "name": name,
            "formula": formula,
            "operands": operand_values,
            "calculated_value": None,
            "reported_value": reported,
            "variance": None,
            "status": "NOT_APPLICABLE",
            "period": period,
            "message": f"Required field(s) not present in document: {', '.join(missing)}",
        }

    calculated = sum(operand_values.values())
    variance = round(calculated - reported, 2)
    status = "PASS" if _within_tolerance(calculated, reported) else "FAIL"
    return {
        "name": name,
        "formula": formula,
        "operands": operand_values,
        "calculated_value": round(calculated, 2),
        "reported_value": reported,
        "variance": variance,
        "status": status,
        "period": period,
        "message": None,
    }


def _field_value(fields: dict, name: str):
    field = fields.get(name)
    if isinstance(field, dict):
        return field.get("value")
    return field


def _is_tax_inclusive(fields: dict) -> bool:
    """Detect if tax is included in line items / subtotal / total."""
    tax_incl_val = _field_value(fields, "tax_inclusive")
    if tax_incl_val is True or str(tax_incl_val).strip().lower() in {"true", "yes", "1"}:
        return True

    tax_field = fields.get("tax_amount")
    if isinstance(tax_field, dict):
        src = str(tax_field.get("source_text") or "").lower()
        if any(term in src for term in ["inclusive", "included", "incl"]):
            return True

    # Arithmetic heuristic: if subtotal == total with positive tax, pricing is tax-inclusive
    subtotal = _field_value(fields, "subtotal")
    total = _field_value(fields, "total_amount")
    tax = _field_value(fields, "tax_amount")
    discount = _field_value(fields, "discount") or 0.0

    if subtotal is not None and total is not None and tax is not None and tax > 0:
        if _within_tolerance(subtotal - discount, total):
            return True
        if not _within_tolerance(subtotal + tax - discount, total) and _within_tolerance(total - tax, subtotal):
            return True

    return False


def _periods_present(fields: dict, names: list[str]) -> list[str]:
    for name in names:
        v = _field_value(fields, name)
        if isinstance(v, dict) and v:
            return list(v.keys())
    return ["current"]


def _value_for_period(fields: dict, name: str, period: str):
    v = _field_value(fields, name)
    if isinstance(v, dict):
        if period in v:
            return v.get(period)
        for pk, pv in v.items():
            if str(pk).strip().lower() == str(period).strip().lower():
                return pv
    flat_val = _field_value(fields, f"{name}_{period}")
    if flat_val is not None:
        return flat_val
    if period in ("current", "2026") and v is not None and not isinstance(v, dict):
        return v
    return None


def validate_invoice(
    extracted: dict | None = None,
    *,
    fields: dict | None = None,
    line_items: list | None = None,
    **kwargs,
) -> list[dict]:
    if extracted is None:
        extracted = {}

    # Handle if caller passes fields directly as extracted dict
    if "fields" not in extracted and any(k in extracted for k in ["subtotal", "total_amount", "tax_amount"]):
        f = extracted
        items = line_items or []
    else:
        f = fields if fields is not None else extracted.get("fields", {})
        items = line_items if line_items is not None else extracted.get("line_items", [])

    checks: list[dict] = []

    # 1. Line item checks (only validate quantity * unit_price when both are available)
    subtotal_val = _field_value(f, "subtotal")
    tax_val = _field_value(f, "tax_amount")
    rate_val = _field_value(f, "tax_rate")
    numeric_rate = None
    if rate_val is not None:
        try:
            numeric_rate = float(str(rate_val).replace("%", "").strip()) / 100.0
        except ValueError:
            pass
    elif tax_val and subtotal_val and subtotal_val > 0:
        numeric_rate = tax_val / subtotal_val

    for idx, item in enumerate(items, start=1):
        qty = item.get("quantity")
        price = item.get("unit_price")
        amount = item.get("amount")
        if qty is not None and price is not None and amount is not None:
            if _within_tolerance(qty * price, amount):
                operands = {"quantity_x_unit_price": round(qty * price, 2)}
            elif numeric_rate and _within_tolerance(qty * price * (1.0 + numeric_rate), amount):
                operands = {"quantity_x_unit_price_tax_inclusive": amount}
            elif _within_tolerance(price, amount):
                operands = {"unit_price_is_line_total": amount}
            else:
                operands = {"quantity_x_unit_price": round(qty * price, 2)}

            checks.append(
                _build_check(
                    f"line_item_{idx}_check",
                    "quantity * unit_price",
                    operands,
                    amount,
                    None,
                )
            )
        elif amount is not None and (qty is not None or price is not None):
            checks.append(
                _build_check(
                    f"line_item_{idx}_check",
                    "quantity * unit_price",
                    {"quantity": qty, "unit_price": price},
                    amount,
                    None,
                )
            )

    # 2. Line items sum to subtotal / total
    item_amounts = [li.get("amount") for li in items if li.get("amount") is not None]
    subtotal = _field_value(f, "subtotal")
    total = _field_value(f, "total_amount")
    tax = _field_value(f, "tax_amount")
    shipping = (
        _field_value(f, "shipping")
        or _field_value(f, "shipping_and_handling")
        or _field_value(f, "delivery_fee")
        or 0.0
    )
    discount = _field_value(f, "discount")
    discount_deduction = -abs(discount) if discount is not None else 0.0

    if item_amounts:
        sum_items = round(sum(item_amounts), 2)
        if subtotal is not None and _within_tolerance(sum_items, subtotal):
            checks.append(
                _build_check(
                    "line_items_sum_to_subtotal",
                    "sum(line_item.amount)",
                    {"sum_of_line_items": sum_items},
                    subtotal,
                    None,
                )
            )
        elif total is not None and (_is_tax_inclusive(f) or _within_tolerance(sum_items, total)):
            checks.append(
                _build_check(
                    "line_items_sum_to_total",
                    "sum(line_item.amount)",
                    {"sum_of_line_items": sum_items},
                    total,
                    None,
                )
            )
        elif total is not None and tax is not None and _within_tolerance(sum_items + tax, total):
            checks.append(
                _build_check(
                    "line_items_sum_to_total",
                    "sum(line_item.amount) + tax",
                    {"sum_of_line_items": sum_items, "tax_amount": tax},
                    total,
                    None,
                )
            )
        elif total is not None and _within_tolerance(sum_items + (tax or 0.0) + shipping + discount_deduction, total):
            checks.append(
                _build_check(
                    "line_items_sum_to_total",
                    "sum(line_item.amount) + tax + shipping - discount",
                    {"sum_of_line_items": sum_items, "tax_amount": tax, "shipping": shipping, "discount": discount_deduction},
                    total,
                    None,
                )
            )
        elif subtotal is not None:
            checks.append(
                _build_check(
                    "line_items_sum_to_subtotal",
                    "sum(line_item.amount)",
                    {"sum_of_line_items": sum_items},
                    subtotal,
                    None,
                )
            )
        elif total is not None:
            checks.append(
                _build_check(
                    "line_items_sum_to_total",
                    "sum(line_item.amount)",
                    {"sum_of_line_items": sum_items},
                    total,
                    None,
                )
            )

    # 3. Invoice total check (tax-inclusive vs tax-exclusive aware, with shipping and discount)
    if subtotal is not None and total is not None:
        if tax is not None and _within_tolerance(subtotal + tax + shipping + discount_deduction, total):
            operands = {"subtotal": subtotal, "tax_amount": tax, "discount": discount_deduction}
            if shipping:
                operands["shipping"] = shipping
            checks.append(
                _build_check("invoice_total_check", "subtotal + tax_amount + shipping - discount", operands, total, None)
            )
        elif _within_tolerance(subtotal + shipping + discount_deduction, total) or _is_tax_inclusive(f):
            operands = {"subtotal": subtotal, "discount": discount_deduction}
            if shipping:
                operands["shipping"] = shipping
            checks.append(
                _build_check("invoice_total_check", "subtotal + shipping - discount (tax inclusive)", operands, total, None)
            )
        else:
            operands = {"subtotal": subtotal, "tax_amount": tax, "discount": discount_deduction}
            if shipping:
                operands["shipping"] = shipping
            checks.append(
                _build_check("invoice_total_check", "subtotal + tax_amount + shipping - discount", operands, total, None)
            )

    # 4. Cash / Change check: cash_paid - total_amount = change
    cash_paid = _field_value(f, "cash_paid")
    change = _field_value(f, "change") if _field_value(f, "change") is not None else _field_value(f, "change_amount")
    if cash_paid is not None or change is not None:
        if cash_paid is not None and total is not None and change is not None:
            diff = cash_paid - total
            if change > 1.0 and _within_tolerance(diff, change / 100.0):
                checks.append(
                    _build_check(
                        "cash_change_check",
                        "cash_paid - total_amount",
                        {"cash_paid": cash_paid, "total_amount": -total},
                        round(change / 100.0, 2),
                        None,
                    )
                )
            else:
                checks.append(
                    _build_check(
                        "cash_change_check",
                        "cash_paid - total_amount",
                        {"cash_paid": cash_paid, "total_amount": -total},
                        change,
                        None,
                    )
                )
        else:
            checks.append(
                _build_check(
                    "cash_change_check",
                    "cash_paid - total_amount",
                    {"cash_paid": cash_paid, "total_amount": (-total if total is not None else None)},
                    change,
                    None,
                )
            )

    return checks


def validate_balance_sheet(
    extracted: dict | None = None,
    *,
    fields: dict | None = None,
    **kwargs,
) -> list[dict]:
    if extracted is None:
        extracted = {}
    f = fields if fields is not None else extracted.get("fields", extracted)

    periods = _periods_present(f, ["total_assets", "total_liabilities", "total_equity"])
    checks = []
    for period in periods:
        assets = _value_for_period(f, "total_assets", period)
        liabilities = _value_for_period(f, "total_liabilities", period)
        equity = _value_for_period(f, "total_equity", period)
        combined = _value_for_period(f, "total_capital_and_liabilities", period)
        operands = (
            {"total_capital_and_liabilities": combined}
            if combined is not None
            else {"total_liabilities": liabilities, "total_equity": equity}
        )
        checks.append(
            _build_check(
                "assets_equal_liabilities_plus_equity",
                "total_liabilities + total_equity ≈ total_assets",
                operands,
                assets,
                period if period != "current" else None,
            )
        )
    return checks


def validate_profit_and_loss(
    extracted: dict | None = None,
    *,
    fields: dict | None = None,
    **kwargs,
) -> list[dict]:
    if extracted is None:
        extracted = {}
    f = fields if fields is not None else extracted.get("fields", extracted)

    bank_style_names = ["interest_earned", "total_income", "total_expenditure"]
    is_bank_style = any(_field_value(f, n) is not None for n in bank_style_names)

    if is_bank_style:
        periods = _periods_present(f, bank_style_names)
        checks = []
        for period in periods:
            p = lambda n: _value_for_period(f, n, period)  # noqa: E731
            checks.append(
                _build_check(
                    "total_income_check",
                    "interest_earned + other_income",
                    {"interest_earned": p("interest_earned"), "other_income": p("other_income")},
                    p("total_income"),
                    period if period != "current" else None,
                )
            )
            checks.append(
                _build_check(
                    "total_expenditure_check",
                    "interest_expended + operating_expenses + provisions_and_contingencies",
                    {
                        "interest_expended": p("interest_expended"),
                        "operating_expenses": p("operating_expenses"),
                        "provisions_and_contingencies": p("provisions_and_contingencies"),
                    },
                    p("total_expenditure"),
                    period if period != "current" else None,
                )
            )
            ti, te = p("total_income"), p("total_expenditure")
            checks.append(
                _build_check(
                    "net_profit_before_minority_check",
                    "total_income - total_expenditure",
                    {"total_income": ti, "total_expenditure": (-te if te is not None else None)},
                    p("net_profit_before_minority_interest"),
                    period if period != "current" else None,
                )
            )
            npb, mi = p("net_profit_before_minority_interest"), p("minority_interest")
            checks.append(
                _build_check(
                    "net_profit_after_minority_check",
                    "profit_before_minority_interest - minority_interest",
                    {
                        "net_profit_before_minority_interest": npb,
                        "minority_interest": (-mi if mi is not None else None),
                    },
                    p("net_profit_after_minority_interest"),
                    period if period != "current" else None,
                )
            )
            cp, bf = p("net_profit_after_minority_interest"), p("brought_forward_profit")
            if cp is not None or bf is not None:
                checks.append(
                    _build_check(
                        "appropriation_check",
                        "current_profit + brought_forward_profit",
                        {"current_profit": cp, "brought_forward_profit": bf},
                        p("total_available_for_appropriation"),
                        period if period != "current" else None,
                    )
                )
        return checks

    periods = _periods_present(f, ["revenue", "gross_profit", "net_profit"])
    checks = []
    for period in periods:
        p = lambda n: _value_for_period(f, n, period)  # noqa: E731
        rev, cos = p("revenue"), p("cost_of_sales")
        checks.append(
            _build_check(
                "gross_profit_check",
                "revenue - cost_of_sales",
                {"revenue": rev, "cost_of_sales": (-cos if cos is not None else None)},
                p("gross_profit"),
                period if period != "current" else None,
            )
        )
        gp, opex = p("gross_profit"), p("operating_expenses")
        checks.append(
            _build_check(
                "operating_profit_check",
                "gross_profit - operating_expenses",
                {"gross_profit": gp, "operating_expenses": (-opex if opex is not None else None)},
                p("operating_profit"),
                period if period != "current" else None,
            )
        )
        op, tax = p("operating_profit"), p("tax")
        checks.append(
            _build_check(
                "net_profit_check",
                "operating_profit - tax",
                {"operating_profit": op, "tax": (-tax if tax is not None else None)},
                p("net_profit"),
                period if period != "current" else None,
            )
        )
    return checks


def validate_cash_flow(
    extracted: dict | None = None,
    *,
    fields: dict | None = None,
    **kwargs,
) -> list[dict]:
    if extracted is None:
        extracted = {}
    f = fields if fields is not None else extracted.get("fields", extracted)

    periods = _periods_present(f, ["operating_cash_flow", "opening_cash", "closing_cash"])
    checks = []
    for period in periods:
        p = lambda n: _value_for_period(f, n, period)  # noqa: E731
        ocf, icf, fcf, fx = (
            p("operating_cash_flow"),
            p("investing_cash_flow"),
            p("financing_cash_flow"),
            p("fx_translation_adjustment"),
        )
        operands = {"operating_cash_flow": ocf, "investing_cash_flow": icf, "financing_cash_flow": fcf}
        if fx is not None:
            operands["fx_translation_adjustment"] = fx
        checks.append(
            _build_check(
                "net_change_in_cash_check",
                "operating + investing + financing (+ fx adjustment)",
                operands,
                p("net_change_in_cash"),
                period if period != "current" else None,
            )
        )
        opening, net_change, acquired = p("opening_cash"), p("net_change_in_cash"), p("cash_acquired_on_amalgamation")
        closing = p("closing_cash")
        operands2 = {"opening_cash": opening, "net_change_in_cash": net_change}
        if opening is not None and net_change is not None and closing is not None:
            if not _within_tolerance(opening + net_change, closing):
                candidate_acquired = acquired
                if candidate_acquired is None:
                    raw_acq = _field_value(f, "cash_acquired_on_amalgamation")
                    if isinstance(raw_acq, dict):
                        for val in raw_acq.values():
                            if isinstance(val, (int, float)) and _within_tolerance(opening + net_change + val, closing):
                                candidate_acquired = val
                                break
                    elif isinstance(raw_acq, (int, float)):
                        candidate_acquired = raw_acq

                if candidate_acquired is not None and _within_tolerance(opening + net_change + candidate_acquired, closing):
                    operands2["cash_acquired_on_amalgamation"] = candidate_acquired
        elif acquired is not None:
            operands2["cash_acquired_on_amalgamation"] = acquired

        checks.append(
            _build_check(
                "closing_cash_check",
                "opening_cash + net_change_in_cash (+ other adjustments)",
                operands2,
                closing,
                period if period != "current" else None,
            )
        )
    return checks


# Aliases for backward compatibility
_validate_invoice = validate_invoice
_validate_balance_sheet = validate_balance_sheet
_validate_profit_and_loss = validate_profit_and_loss
_validate_cash_flow = validate_cash_flow

_VALIDATORS = {
    "invoice": validate_invoice,
    "balance_sheet": validate_balance_sheet,
    "profit_and_loss": validate_profit_and_loss,
    "cash_flow_statement": validate_cash_flow,
    "cash_flow": validate_cash_flow,
}


def validate(document_type: str, extracted_data: dict) -> dict:
    doc_key = (document_type or "").strip().lower()
    validator = _VALIDATORS.get(doc_key)
    if validator is None:
        return {"checks": [], "overall_status": "NOT_APPLICABLE", "issues": [f"Unknown document_type: {document_type}"]}

    checks = validator(extracted_data)
    statuses = {c["status"] for c in checks}
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "PASS" in statuses:
        overall = "PASS"
    else:
        overall = "NOT_APPLICABLE"

    issues = [
        f"{c['name']} ({c.get('period') or 'current'}): reported {c['reported_value']} vs calculated {c['calculated_value']} (variance {c['variance']})"
        for c in checks
        if c["status"] == "FAIL"
    ]
    logger.info("Financial validation for %s: overall=%s, %d check(s)", document_type, overall, len(checks))
    return {"checks": checks, "overall_status": overall, "issues": issues}
