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
    if not isinstance(field, dict):
        return None
    return field.get("value")


def _periods_present(fields: dict, names: list[str]) -> list[str]:
    for name in names:
        v = _field_value(fields, name)
        if isinstance(v, dict) and v:
            return list(v.keys())
    return ["current"]


def _value_for_period(fields: dict, name: str, period: str):
    v = _field_value(fields, name)
    if isinstance(v, dict):
        return v.get(period)
    return v if period == "current" else None


def _validate_invoice(extracted: dict) -> list[dict]:
    fields = extracted.get("fields", {})
    line_items = extracted.get("line_items", [])
    checks: list[dict] = []

    for idx, item in enumerate(line_items, start=1):
        qty, price, amount = item.get("quantity"), item.get("unit_price"), item.get("amount")
        checks.append(
            _build_check(
                f"line_item_{idx}_check",
                "quantity * unit_price",
                {"quantity_x_unit_price": (qty * price) if qty is not None and price is not None else None},
                amount,
                None,
            )
        )

    if line_items and all(li.get("amount") is not None for li in line_items):
        subtotal = _field_value(fields, "subtotal")
        checks.append(
            _build_check(
                "line_items_sum_to_subtotal",
                "sum(line_item.amount)",
                {"sum_of_line_items": sum(li["amount"] for li in line_items)},
                subtotal,
                None,
            )
        )

    subtotal = _field_value(fields, "subtotal")
    tax = _field_value(fields, "tax_amount")
    discount = _field_value(fields, "discount")
    total = _field_value(fields, "total_amount")
    operands = {"subtotal": subtotal, "tax_amount": tax, "discount": (-discount if discount is not None else None)}
    checks.append(_build_check("invoice_total_check", "subtotal + tax_amount - discount", operands, total, None))

    cash_paid = _field_value(fields, "cash_paid")
    change = _field_value(fields, "change") or _field_value(fields, "change_amount")
    if cash_paid is not None or change is not None:
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


def _validate_balance_sheet(extracted: dict) -> list[dict]:
    fields = extracted.get("fields", {})
    periods = _periods_present(fields, ["total_assets", "total_liabilities", "total_equity"])
    checks = []
    for period in periods:
        assets = _value_for_period(fields, "total_assets", period)
        liabilities = _value_for_period(fields, "total_liabilities", period)
        equity = _value_for_period(fields, "total_equity", period)
        combined = _value_for_period(fields, "total_capital_and_liabilities", period)
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


def _validate_profit_and_loss(extracted: dict) -> list[dict]:
    fields = extracted.get("fields", {})
    bank_style_names = ["interest_earned", "total_income", "total_expenditure"]
    is_bank_style = any(_field_value(fields, n) is not None for n in bank_style_names)

    if is_bank_style:
        periods = _periods_present(fields, bank_style_names)
        checks = []
        for period in periods:
            p = lambda n: _value_for_period(fields, n, period)  # noqa: E731
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

    periods = _periods_present(fields, ["revenue", "gross_profit", "net_profit"])
    checks = []
    for period in periods:
        p = lambda n: _value_for_period(fields, n, period)  # noqa: E731
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


def _validate_cash_flow(extracted: dict) -> list[dict]:
    fields = extracted.get("fields", {})
    periods = _periods_present(fields, ["operating_cash_flow", "opening_cash", "closing_cash"])
    checks = []
    for period in periods:
        p = lambda n: _value_for_period(fields, n, period)  # noqa: E731
        ocf, icf, fcf, fx = p("operating_cash_flow"), p("investing_cash_flow"), p("financing_cash_flow"), p("fx_translation_adjustment")
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
        operands2 = {"opening_cash": opening, "net_change_in_cash": net_change}
        if acquired is not None:
            operands2["cash_acquired_on_amalgamation"] = acquired
        checks.append(
            _build_check(
                "closing_cash_check",
                "opening_cash + net_change_in_cash (+ other adjustments)",
                operands2,
                p("closing_cash"),
                period if period != "current" else None,
            )
        )
    return checks


_VALIDATORS = {
    "invoice": _validate_invoice,
    "balance_sheet": _validate_balance_sheet,
    "profit_and_loss": _validate_profit_and_loss,
    "cash_flow_statement": _validate_cash_flow,
}


def validate(document_type: str, extracted_data: dict) -> dict:
    validator = _VALIDATORS.get(document_type)
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
