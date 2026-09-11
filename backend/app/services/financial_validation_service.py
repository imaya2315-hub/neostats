"""
Financial calculation validation.

Validation is deterministic and never changes extracted values.

If required values are missing, the check is NOT_APPLICABLE.
If values are present, arithmetic is performed and compared against
the reported value using the configured tolerance.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger("docintel.validation.financial")


def _within_tolerance(
    calculated: float,
    reported: float,
) -> bool:
    settings = get_settings()

    tolerance = max(
        settings.VALIDATION_ABS_TOLERANCE,
        settings.VALIDATION_PCT_TOLERANCE * abs(reported),
    )

    return abs(calculated - reported) <= tolerance


def _build_check(
    name: str,
    formula: str,
    operand_values: dict[str, float | None],
    reported,
    period: str | None,
) -> dict:

    missing = [
        key
        for key, value in operand_values.items()
        if value is None
    ]

    if reported is None:
        missing.append("reported_value")

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
            "message": (
                "Required field(s) not present in document: "
                + ", ".join(missing)
            ),
        }

    calculated = sum(
        operand_values.values()
    )

    variance = round(
        calculated - reported,
        2,
    )

    status = (
        "PASS"
        if _within_tolerance(
            calculated,
            reported,
        )
        else "FAIL"
    )

    return {
        "name": name,
        "formula": formula,
        "operands": operand_values,
        "calculated_value": round(
            calculated,
            2,
        ),
        "reported_value": reported,
        "variance": variance,
        "status": status,
        "period": period,
        "message": None,
    }


def _field_value(
    fields: dict,
    name: str,
):
    field = fields.get(name)

    if not isinstance(field, dict):
        return None

    return field.get("value")


def _periods_present(
    fields: dict,
    names: list[str],
) -> list[str]:

    for name in names:

        value = _field_value(
            fields,
            name,
        )

        if isinstance(value, dict) and value:
            return list(value.keys())

    return ["current"]


def _value_for_period(
    fields: dict,
    name: str,
    period: str,
):
    value = _field_value(
        fields,
        name,
    )

    if isinstance(value, dict):
        return value.get(period)

    return (
        value
        if period == "current"
        else None
    )


def validate_invoice_financials(
    fields: dict,
    line_items: list[dict],
) -> dict:
    checks = []
    issues = []

    def value(name):
        field = fields.get(name)
        if isinstance(field, dict):
            return field.get("value")
        return field

    def num(v):
        if isinstance(v, (int, float)):
            return float(v)
        return None

    def check_line_item(index, item):
        quantity = num(item.get("quantity"))
        unit_price = num(item.get("unit_price"))
        amount = num(item.get("amount"))

        calculated = None
        variance = None
        status = "NOT_APPLICABLE"
        message = None

        if quantity is not None and unit_price is not None:
            calculated = round(quantity * unit_price, 2)

            if amount is not None:
                variance = round(calculated - amount, 2)
                status = "PASS" if abs(variance) <= 0.05 else "FAIL"

                if status == "FAIL":
                    message = (
                        f"Line item amount does not match "
                        f"quantity × unit price: expected {calculated}, "
                        f"reported {amount}."
                    )
            else:
                status = "NOT_APPLICABLE"
                message = "Line item amount is not present."

        else:
            message = (
                "Required field(s) not present in document: "
                "quantity_x_unit_price"
            )

        return {
            "name": f"line_item_{index}_check",
            "formula": "quantity * unit_price",
            "operands": {
                "quantity_x_unit_price": calculated
            },
            "calculated_value": calculated,
            "reported_value": amount,
            "variance": variance,
            "status": status,
            "period": None,
            "message": message,
        }

    for index, item in enumerate(line_items, start=1):
        check = check_line_item(index, item)
        checks.append(check)

        if check["status"] == "FAIL":
            issues.append(
                f'{check["name"]}: {check["message"]}'
            )

    amounts = [
        num(item.get("amount"))
        for item in line_items
        if num(item.get("amount")) is not None
    ]

    subtotal = num(value("subtotal"))

    if amounts:
        line_item_sum = round(sum(amounts), 2)

        if subtotal is not None:
            variance = round(line_item_sum - subtotal, 2)
            status = "PASS" if abs(variance) <= 0.05 else "FAIL"

            checks.append({
                "name": "line_items_sum_to_subtotal",
                "formula": "sum(line_item.amount)",
                "operands": {
                    "sum_of_line_items": line_item_sum
                },
                "calculated_value": line_item_sum,
                "reported_value": subtotal,
                "variance": variance,
                "status": status,
                "period": None,
                "message": None,
            })

            if status == "FAIL":
                issues.append(
                    f"line_items_sum_to_subtotal: "
                    f"reported {subtotal} vs calculated "
                    f"{line_item_sum} (variance {variance})"
                )
        else:
            checks.append({
                "name": "line_items_sum_to_subtotal",
                "formula": "sum(line_item.amount)",
                "operands": {
                    "sum_of_line_items": line_item_sum
                },
                "calculated_value": line_item_sum,
                "reported_value": None,
                "variance": None,
                "status": "NOT_APPLICABLE",
                "period": None,
                "message": "Subtotal is not present.",
            })
    else:
        checks.append({
            "name": "line_items_sum_to_subtotal",
            "formula": "sum(line_item.amount)",
            "operands": {
                "sum_of_line_items": None
            },
            "calculated_value": None,
            "reported_value": subtotal,
            "variance": None,
            "status": "NOT_APPLICABLE",
            "period": None,
            "message": "No line item amounts are available.",
        })

    tax = num(value("tax_amount"))
    discount = num(value("discount"))
    total = num(value("total_amount"))

    if subtotal is not None and tax is not None and total is not None:
        effective_discount = discount if discount is not None else 0.0

        calculated_total = round(
            subtotal + tax - effective_discount,
            2,
        )

        variance = round(
            calculated_total - total,
            2,
        )

        status = (
            "PASS"
            if abs(variance) <= 0.05
            else "FAIL"
        )

        checks.append({
            "name": "invoice_total_check",
            "formula": "subtotal + tax_amount - discount",
            "operands": {
                "subtotal": subtotal,
                "tax_amount": tax,
                "discount": effective_discount,
            },
            "calculated_value": calculated_total,
            "reported_value": total,
            "variance": variance,
            "status": status,
            "period": None,
            "message": None,
        })

        if status == "FAIL":
            issues.append(
                f"invoice_total_check: "
                f"reported {total} vs calculated "
                f"{calculated_total} (variance {variance})"
            )
    else:
        missing = []

        if subtotal is None:
            missing.append("subtotal")

        if tax is None:
            missing.append("tax_amount")

        if total is None:
            missing.append("total_amount")

        checks.append({
            "name": "invoice_total_check",
            "formula": "subtotal + tax_amount - discount",
            "operands": {
                "subtotal": subtotal,
                "tax_amount": tax,
                "discount": discount,
            },
            "calculated_value": None,
            "reported_value": total,
            "variance": None,
            "status": "NOT_APPLICABLE",
            "period": None,
            "message": (
                "Required field(s) not present in document: "
                + ", ".join(missing)
            ),
        })

    cash_paid = num(value("cash_paid"))
    change = num(value("change"))

    if cash_paid is not None and total is not None:
        calculated_change = round(
            cash_paid - total,
            2,
        )

        if change is not None:
            variance = round(
                calculated_change - change,
                2,
            )

            status = (
                "PASS"
                if abs(variance) <= 0.05
                else "FAIL"
            )

            message = None

            if status == "FAIL":
                message = (
                    f"Extracted change does not match "
                    f"cash paid minus invoice total: "
                    f"expected {calculated_change}, "
                    f"reported {change}."
                )

            checks.append({
                "name": "cash_change_check",
                "formula": "cash_paid - total_amount",
                "operands": {
                    "cash_paid": cash_paid,
                    "total_amount": total,
                },
                "calculated_value": calculated_change,
                "reported_value": change,
                "variance": variance,
                "status": status,
                "period": None,
                "message": message,
            })

            if status == "FAIL":
                issues.append(
                    f"cash_change_check: "
                    f"reported {change} vs calculated "
                    f"{calculated_change} "
                    f"(variance {variance})"
                )
        else:
            checks.append({
                "name": "cash_change_check",
                "formula": "cash_paid - total_amount",
                "operands": {
                    "cash_paid": cash_paid,
                    "total_amount": total,
                },
                "calculated_value": calculated_change,
                "reported_value": None,
                "variance": None,
                "status": "NOT_APPLICABLE",
                "period": None,
                "message": "Change is not present.",
            })
    else:
        checks.append({
            "name": "cash_change_check",
            "formula": "cash_paid - total_amount",
            "operands": {
                "cash_paid": cash_paid,
                "total_amount": total,
            },
            "calculated_value": None,
            "reported_value": change,
            "variance": None,
            "status": "NOT_APPLICABLE",
            "period": None,
            "message": (
                "Required field(s) not present in document: "
                "cash_paid or total_amount"
            ),
        })

    overall_status = (
        "FAIL"
        if issues
        else "PASS"
    )

    return {
        "checks": checks,
        "overall_status": overall_status,
        "issues": issues,
    }

def _validate_balance_sheet(
    extracted: dict,
) -> list[dict]:

    fields = extracted.get(
        "fields",
        {},
    )

    periods = _periods_present(
        fields,
        [
            "total_assets",
            "total_liabilities",
            "total_equity",
        ],
    )

    checks = []

    for period in periods:

        assets = _value_for_period(
            fields,
            "total_assets",
            period,
        )

        liabilities = _value_for_period(
            fields,
            "total_liabilities",
            period,
        )

        equity = _value_for_period(
            fields,
            "total_equity",
            period,
        )

        combined = _value_for_period(
            fields,
            "total_capital_and_liabilities",
            period,
        )

        operands = (
            {
                "total_capital_and_liabilities":
                    combined
            }
            if combined is not None
            else {
                "total_liabilities":
                    liabilities,
                "total_equity":
                    equity,
            }
        )

        checks.append(
            _build_check(
                "assets_equal_liabilities_plus_equity",
                "total_liabilities + total_equity ≈ total_assets",
                operands,
                assets,
                (
                    period
                    if period != "current"
                    else None
                ),
            )
        )

    return checks


def _validate_profit_and_loss(
    extracted: dict,
) -> list[dict]:

    fields = extracted.get(
        "fields",
        {},
    )

    bank_style_names = [
        "interest_earned",
        "total_income",
        "total_expenditure",
    ]

    is_bank_style = any(
        _field_value(fields, name) is not None
        for name in bank_style_names
    )

    if is_bank_style:

        periods = _periods_present(
            fields,
            bank_style_names,
        )

        checks = []

        for period in periods:

            p = lambda n: _value_for_period(
                fields,
                n,
                period,
            )

            checks.append(
                _build_check(
                    "total_income_check",
                    "interest_earned + other_income",
                    {
                        "interest_earned":
                            p("interest_earned"),
                        "other_income":
                            p("other_income"),
                    },
                    p("total_income"),
                    (
                        period
                        if period != "current"
                        else None
                    ),
                )
            )

            checks.append(
                _build_check(
                    "total_expenditure_check",
                    "interest_expended + operating_expenses + provisions_and_contingencies",
                    {
                        "interest_expended":
                            p("interest_expended"),
                        "operating_expenses":
                            p("operating_expenses"),
                        "provisions_and_contingencies":
                            p(
                                "provisions_and_contingencies"
                            ),
                    },
                    p("total_expenditure"),
                    (
                        period
                        if period != "current"
                        else None
                    ),
                )
            )

            checks.append(
                _build_check(
                    "net_profit_before_minority_check",
                    "total_income - total_expenditure",
                    {
                        "total_income":
                            p("total_income"),
                        "total_expenditure":
                            (
                                -p("total_expenditure")
                                if p("total_expenditure")
                                is not None
                                else None
                            ),
                    },
                    p(
                        "net_profit_before_minority_interest"
                    ),
                    (
                        period
                        if period != "current"
                        else None
                    ),
                )
            )

            checks.append(
                _build_check(
                    "net_profit_after_minority_check",
                    "profit_before_minority_interest - minority_interest",
                    {
                        "net_profit_before_minority_interest":
                            p(
                                "net_profit_before_minority_interest"
                            ),
                        "minority_interest":
                            (
                                -p("minority_interest")
                                if p("minority_interest")
                                is not None
                                else None
                            ),
                    },
                    p(
                        "net_profit_after_minority_interest"
                    ),
                    (
                        period
                        if period != "current"
                        else None
                    ),
                )
            )

            current_profit = p(
                "net_profit_after_minority_interest"
            )

            brought_forward = p(
                "brought_forward_profit"
            )

            if (
                current_profit is not None
                or brought_forward is not None
            ):

                checks.append(
                    _build_check(
                        "appropriation_check",
                        "current_profit + brought_forward_profit",
                        {
                            "current_profit":
                                current_profit,
                            "brought_forward_profit":
                                brought_forward,
                        },
                        p(
                            "total_available_for_appropriation"
                        ),
                        (
                            period
                            if period != "current"
                            else None
                        ),
                    )
                )

        return checks

    # Standard P&L.
    periods = _periods_present(
        fields,
        [
            "revenue",
            "gross_profit",
            "net_profit",
        ],
    )

    checks = []

    for period in periods:

        p = lambda n: _value_for_period(
            fields,
            n,
            period,
        )

        revenue = p("revenue")
        cost_of_sales = p(
            "cost_of_sales"
        )

        checks.append(
            _build_check(
                "gross_profit_check",
                "revenue - cost_of_sales",
                {
                    "revenue": revenue,
                    "cost_of_sales":
                        (
                            -cost_of_sales
                            if cost_of_sales is not None
                            else None
                        ),
                },
                p("gross_profit"),
                (
                    period
                    if period != "current"
                    else None
                ),
            )
        )

        gross_profit = p(
            "gross_profit"
        )

        operating_expenses = p(
            "operating_expenses"
        )

        checks.append(
            _build_check(
                "operating_profit_check",
                "gross_profit - operating_expenses",
                {
                    "gross_profit":
                        gross_profit,
                    "operating_expenses":
                        (
                            -operating_expenses
                            if operating_expenses is not None
                            else None
                        ),
                },
                p("operating_profit"),
                (
                    period
                    if period != "current"
                    else None
                ),
            )
        )

        operating_profit = p(
            "operating_profit"
        )

        tax = p("tax")

        checks.append(
            _build_check(
                "net_profit_check",
                "operating_profit - tax",
                {
                    "operating_profit":
                        operating_profit,
                    "tax":
                        (
                            -tax
                            if tax is not None
                            else None
                        ),
                },
                p("net_profit"),
                (
                    period
                    if period != "current"
                    else None
                ),
            )
        )

    return checks


def _validate_cash_flow(
    extracted: dict,
) -> list[dict]:

    fields = extracted.get(
        "fields",
        {},
    )

    periods = _periods_present(
        fields,
        [
            "operating_cash_flow",
            "opening_cash",
            "closing_cash",
        ],
    )

    checks = []

    for period in periods:

        p = lambda n: _value_for_period(
            fields,
            n,
            period,
        )

        ocf = p(
            "operating_cash_flow"
        )

        icf = p(
            "investing_cash_flow"
        )

        fcf = p(
            "financing_cash_flow"
        )

        fx = p(
            "fx_translation_adjustment"
        )

        operands = {
            "operating_cash_flow": ocf,
            "investing_cash_flow": icf,
            "financing_cash_flow": fcf,
        }

        if fx is not None:
            operands[
                "fx_translation_adjustment"
            ] = fx

        checks.append(
            _build_check(
                "net_change_in_cash_check",
                "operating + investing + financing (+ fx adjustment)",
                operands,
                p("net_change_in_cash"),
                (
                    period
                    if period != "current"
                    else None
                ),
            )
        )

        opening = p(
            "opening_cash"
        )

        net_change = p(
            "net_change_in_cash"
        )

        acquired = p(
            "cash_acquired_on_amalgamation"
        )

        operands2 = {
            "opening_cash": opening,
            "net_change_in_cash": net_change,
        }

        if acquired is not None:
            operands2[
                "cash_acquired_on_amalgamation"
            ] = acquired

        checks.append(
            _build_check(
                "closing_cash_check",
                "opening_cash + net_change_in_cash (+ other adjustments)",
                operands2,
                p("closing_cash"),
                (
                    period
                    if period != "current"
                    else None
                ),
            )
        )

    return checks


_VALIDATORS = {
    "invoice": _validate_invoice,
    "balance_sheet": _validate_balance_sheet,
    "profit_and_loss": _validate_profit_and_loss,
    "cash_flow_statement": _validate_cash_flow,
}


def validate(
    document_type: str,
    extracted_data: dict,
) -> dict:

    validator = _VALIDATORS.get(
        document_type
    )

    if validator is None:
        return {
            "checks": [],
            "overall_status": "NOT_APPLICABLE",
            "issues": [
                f"Unknown document_type: {document_type}"
            ],
        }

    checks = validator(
        extracted_data
    )

    statuses = {
        check["status"]
        for check in checks
    }

    if "FAIL" in statuses:
        overall = "FAIL"
    elif "PASS" in statuses:
        overall = "PASS"
    else:
        overall = "NOT_APPLICABLE"

    issues = [
        (
            f"{check['name']} "
            f"({check.get('period') or 'current'}): "
            f"reported {check['reported_value']} "
            f"vs calculated {check['calculated_value']} "
            f"(variance {check['variance']})"
        )
        for check in checks
        if check["status"] == "FAIL"
    ]

    logger.info(
        "Financial validation for %s: overall=%s, %d check(s)",
        document_type,
        overall,
        len(checks),
    )

    return {
        "checks": checks,
        "overall_status": overall,
        "issues": issues,
    }
