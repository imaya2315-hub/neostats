"""Unit tests for the extraction-service helpers that can be exercised
without a live LLM call: JSON parsing/salvage, numeric normalization and
page-locating logic."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.extraction_service import (  # noqa: E402
    ExtractionError,
    _locate_page,
    _normalize_numeric,
    _parse_llm_json,
)


def test_parse_llm_json_plain():
    raw = '{"fields": {"total_amount": {"value": 100}}}'
    parsed = _parse_llm_json(raw)
    assert parsed["fields"]["total_amount"]["value"] == 100


def test_parse_llm_json_strips_markdown_fences():
    raw = '```json\n{"fields": {}}\n```'
    parsed = _parse_llm_json(raw)
    assert parsed == {"fields": {}}


def test_parse_llm_json_salvages_embedded_object():
    raw = 'Sure, here is the result:\n{"fields": {"x": {"value": 1}}}\nHope that helps!'
    parsed = _parse_llm_json(raw)
    assert parsed["fields"]["x"]["value"] == 1


def test_parse_llm_json_raises_on_unparsable_text():
    with pytest.raises(ExtractionError):
        _parse_llm_json("not json at all")


def test_normalize_numeric_parses_formatted_string():
    assert _normalize_numeric("1,234.50") == 1234.50


def test_normalize_numeric_parses_parenthesized_negative():
    assert _normalize_numeric("(1,234.50)") == -1234.50


def test_normalize_numeric_passes_through_numbers_and_none():
    assert _normalize_numeric(42) == 42
    assert _normalize_numeric(None) is None


def test_normalize_numeric_recurses_into_dict():
    result = _normalize_numeric({"2025": "1,000.00", "2024": "(500.00)"})
    assert result == {"2025": 1000.0, "2024": -500.0}


def test_locate_page_finds_matching_page():
    pages = ["Invoice number: INV-001", "Total Amount Due: USD 13,125.00"]
    assert _locate_page("Total Amount Due", pages) == 2


def test_locate_page_returns_none_when_no_match():
    pages = ["Invoice number: INV-001"]
    assert _locate_page("nonexistent snippet", pages) is None
