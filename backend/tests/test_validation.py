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
