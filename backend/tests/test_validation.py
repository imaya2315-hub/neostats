"""Unit tests for the two 'pure' validation layers: file integrity and
financial-calculation reconciliation. These do not touch OCR/LLM/DB."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services import financial_validation_service as fvs  # noqa: E402
from app.utils.file_utils import validate_file  # noqa: E402


def test_unsupported_file_type_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    result = validate_file(str(path), "notes.txt")
    assert result.status == "FAILED"
    assert result.error_code == "UNSUPPORTED_FILE_TYPE"


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    result = validate_file(str(path), "empty.pdf")
    assert result.status == "FAILED"
    assert result.error_code == "EMPTY_FILE"


def test_corrupted_pdf_is_rejected(tmp_path):
    path = tmp_path / "bad.pdf"
    path.write_bytes(b"this is not a real pdf")
    result = validate_file(str(path), "bad.pdf")
    assert result.status == "FAILED"
    assert result.error_code == "CORRUPTED_FILE"


def test_invoice_total_check_passes_within_tolerance():
    extracted = {
        "fields": {
            "subtotal": {"value": 12500.00},
            "tax_amount": {"value": 625.00},
            "discount": {"value": 0.00},
            "total_amount": {"value": 13125.00},
        },
        "line_items": [],
    }
    result = fvs.validate("invoice", extracted)
    check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert check["status"] == "PASS"
    assert result["overall_status"] == "PASS"


def test_invoice_total_check_fails_outside_tolerance():
    extracted = {
        "fields": {
            "subtotal": {"value": 12500.00},
            "tax_amount": {"value": 625.00},
            "discount": {"value": 0.00},
            "total_amount": {"value": 14000.00},  # off by 875
        },
        "line_items": [],
    }
    result = fvs.validate("invoice", extracted)
    check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert check["status"] == "FAIL"
    assert result["overall_status"] == "FAIL"


def test_missing_field_yields_not_applicable_not_fail():
    extracted = {
        "fields": {
            "subtotal": {"value": 12500.00},
            "tax_amount": {"value": None},  # not present in document
            "discount": {"value": 0.00},
            "total_amount": {"value": 13125.00},
        },
        "line_items": [],
    }
    result = fvs.validate("invoice", extracted)
    check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert check["status"] == "NOT_APPLICABLE"


def test_balance_sheet_check_per_period():
    extracted = {
        "fields": {
            "total_assets": {"value": {"2025": 1000.0, "2024": 900.0}},
            "total_liabilities": {"value": {"2025": 600.0, "2024": 550.0}},
            "total_equity": {"value": {"2025": 400.0, "2024": 350.0}},
        }
    }
    result = fvs.validate("balance_sheet", extracted)
    assert len(result["checks"]) == 2
    assert all(c["status"] == "PASS" for c in result["checks"])


def test_invoice_tax_inclusive_parking_case():
    """Parking Fee 2.83, GST included 0.17, Total 3.00, Cash 3.00, Change 0.00."""
    extracted = {
        "fields": {
            "subtotal": {"value": 2.83},
            "tax_amount": {"value": 0.17, "source_text": "GST included: 0.17"},
            "total_amount": {"value": 3.00},
            "cash_paid": {"value": 3.00},
            "change": {"value": 0.00},
            "tax_inclusive": {"value": True},
        },
        "line_items": [
            {"description": "Parking Fee", "quantity": None, "unit_price": None, "amount": 2.83}
        ],
    }
    result = fvs.validate("invoice", extracted)
    assert result["overall_status"] == "PASS"
    total_check = next(c for c in result["checks"] if c["name"] == "invoice_total_check")
    assert total_check["status"] == "PASS"
    cash_check = next(c for c in result["checks"] if c["name"] == "cash_change_check")
    assert cash_check["status"] == "PASS"


def test_invoice_teh_cham_clean_case():
    """Teh 2.10, Cham 2.10, Take Away 0.40 -> Subtotal 4.60, Total 4.60, Cash 4.60, Change 0."""
    extracted = {
        "fields": {
            "subtotal": {"value": 4.60},
            "tax_amount": {"value": 0.00},
            "total_amount": {"value": 4.60},
            "cash_paid": {"value": 4.60},
            "change": {"value": 0.00},
        },
        "line_items": [
            {"description": "Teh (B)", "quantity": 1, "unit_price": 2.10, "amount": 2.10},
            {"description": "Cham (B)", "quantity": 1, "unit_price": 2.10, "amount": 2.10},
            {"description": "Take Away", "quantity": 2, "unit_price": 0.20, "amount": 0.40},
        ],
    }
    result = fvs.validate("invoice", extracted)
    assert result["overall_status"] == "PASS"
    assert all(c["status"] == "PASS" for c in result["checks"])


def test_invoice_missing_quantity_does_not_fail():
    """Line items without quantity should be marked NOT_APPLICABLE, not FAIL."""
    extracted = {
        "fields": {
            "subtotal": {"value": 20.08},
            "tax_amount": {"value": 0.99},
            "total_amount": {"value": 20.05},
            "cash_paid": {"value": 26.00},
            "change": {"value": 5.95},
        },
        "line_items": [
            {"description": "Item 1", "quantity": None, "unit_price": None, "amount": 17.44},
            {"description": "Item 2", "quantity": None, "unit_price": None, "amount": 2.64},
        ],
    }
    result = fvs.validate("invoice", extracted)
    # Check that line_item checks are NOT FAIL
    for c in result["checks"]:
        if "line_item_" in c["name"]:
            assert c["status"] == "NOT_APPLICABLE"
    cash_check = next(c for c in result["checks"] if c["name"] == "cash_change_check")
    assert cash_check["status"] == "PASS"


def test_bank_style_profit_and_loss_validation():
    """Consolidated Bank P&L with multi-period checks."""
    extracted = {
        "fields": {
            "interest_earned": {"value": {"2026": 348615.15, "2025": 336367.43}},
            "other_income": {"value": {"2026": 146847.66, "2025": 134548.50}},
            "total_income": {"value": {"2026": 495462.81, "2025": 470915.93}},
            "interest_expended": {"value": {"2026": 185491.23, "2025": 183894.20}},
            "operating_expenses": {"value": {"2026": 181173.91, "2025": 176605.07}},
            "provisions_and_contingencies": {"value": {"2026": 49578.21, "2025": 36976.49}},
            "total_expenditure": {"value": {"2026": 416243.35, "2025": 397475.76}},
            "net_profit_before_minority_interest": {"value": {"2026": 79219.46, "2025": 73440.17}},
            "minority_interest": {"value": {"2026": 3193.49, "2025": 2647.92}},
            "net_profit_after_minority_interest": {"value": {"2026": 76025.97, "2025": 70792.25}},
            "brought_forward_profit": {"value": {"2026": 178692.55, "2025": 150045.57}},
            "total_available_for_appropriation": {"value": {"2026": 254718.52, "2025": 220837.82}},
        }
    }
    result = fvs.validate("profit_and_loss", extracted)
    assert result["overall_status"] == "PASS"
    assert len(result["checks"]) == 10
    assert all(c["status"] == "PASS" for c in result["checks"])


def test_validator_signature_consistency():
    """Verify all validators accept flexible call formats without TypeError."""
    extracted = {"fields": {"total_amount": {"value": 100.0}}, "line_items": []}
    # Direct function calls
    assert isinstance(fvs.validate_invoice(extracted), list)
    assert isinstance(fvs.validate_invoice(fields={"total_amount": {"value": 100.0}}), list)
    assert isinstance(fvs.validate_invoice(fields={}, line_items=[]), list)
    assert isinstance(fvs._validate_invoice(extracted), list)
    assert isinstance(fvs.validate_balance_sheet(extracted), list)
    assert isinstance(fvs.validate_profit_and_loss(extracted), list)
    assert isinstance(fvs.validate_cash_flow(extracted), list)

