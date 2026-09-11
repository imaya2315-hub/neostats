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


def _validate_invoice(
    extracted: dict,
) -> list[dict]:

    fields = extracted.get(
        "fields",
        {},
    )

    line_items = extracted.get(
        "line_items",
        [],
    )

    checks: list[dict] = []



    for idx, item in enumerate(
        line_items,
        start=1,
    ):

        quantity = item.get(
            "quantity"
        )

        unit_price = item.get(
            "unit_price"
        )

        amount = item.get(
            "amount"
        )

        calculated = (
            round(
                quantity * unit_price,
                2,
            )
            if quantity is not None
            and unit_price is not None
            else None
        )

        checks.append(
            _build_check(
                name=f"line_item_{idx}_check",
                formula="quantity * unit_price",
                operand_values={
                    "quantity_x_unit_price":
                        calculated
                },
                reported=amount,
                period=None,
            )
        )

 

    valid_amounts = [
        item.get("amount")
        for item in line_items
        if isinstance(
            item.get("amount"),
            (int, float),
        )
    ]

    subtotal = _field_value(
        fields,
        "subtotal",
    )

    if valid_amounts:

        line_items_total = round(
            sum(valid_amounts),
            2,
        )

        checks.append(
            _build_check(
                name="line_items_sum_to_subtotal",
                formula="sum(line_item.amount)",
                operand_values={
                    "sum_of_line_items":
                        line_items_total
                },
                reported=subtotal,
                period=None,
            )
        )



    tax = _field_value(
        fields,
        "tax_amount",
    )

    discount = _field_value(
        fields,
        "discount",
    )

    total = _field_value(
        fields,
        "total_amount",
    )

    discount_value = (
        discount
        if discount is not None
        else 0
    )

    checks.append(
        _build_check(
            name="invoice_total_check",
            formula="subtotal + tax_amount - discount",
            operand_values={
                "subtotal": subtotal,
                "tax_amount": tax,
                "discount": -discount_value,
            },
            reported=total,
            period=None,
        )
    )


    cash_paid = _field_value(
        fields,
        "cash_paid",
    )

    change = _field_value(
        fields,
        "change",
    )

    if (
        cash_paid is not None
        or change is not None
    ):

        negative_total = (
            -total
            if total is not None
            else None
        )

        check = _build_check(
            name="cash_change_check",
            formula="cash_paid - total_amount",
            operand_values={
                "cash_paid": cash_paid,
                "negative_total_amount":
                    negative_total,
            },
            reported=change,
            period=None,
        )

        if (
            cash_paid is not None
            and total is not None
        ):

            expected_change = round(
                cash_paid - total,
                2,
            )

            check["calculated_value"] = (
                expected_change
            )

            if change is not None:

                check["variance"] = round(
                    expected_change - change,
                    2,
                )

                check["status"] = (
                    "PASS"
                    if _within_tolerance(
                        expected_change,
                        change,
                    )
                    else "FAIL"
                )

                if check["status"] == "FAIL":
                    check["message"] = (
                        "Extracted change does not match "
                        "cash paid minus invoice total: "
                        f"expected {expected_change}, "
                        f"reported {change}."
                    )

        checks.append(check)

    return checks


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
