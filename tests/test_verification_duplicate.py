"""Unit tests for Verification & Compliance — duplicate check (RapidFuzz logic)."""
from pathlib import Path

import pytest
from rapidfuzz import fuzz, process

# Add backend to path
sys_path = __import__("sys").path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys_path:
    sys_path.insert(0, str(_backend))

from agents.verification_compliance.duplicate_check import (
    _normalize_invoice_key,
    DuplicateCheckResult,
)


def test_normalize_invoice_key():
    """Normalize extracted data to (inv_number, total, date)."""
    data = {
        "invoice_number": " INV-001 ",
        "total": 100.50,
        "date": "2024-01-15",
    }
    inv, total, date_val = _normalize_invoice_key(data)
    assert inv == "INV-001"
    assert total == 100.50
    assert date_val == "2024-01-15"


def test_normalize_invoice_key_empty():
    """Empty/missing fields should return empty strings or None."""
    inv, total, date_val = _normalize_invoice_key({})
    assert inv == ""
    assert total is None
    assert date_val == ""


def test_rapidfuzz_threshold_behavior():
    """RapidFuzz WRatio: similar invoice numbers above threshold match."""
    choices = ["INV-2024-001", "INV-2024-002", "INVOICE-100"]
    query = "INV-2024-001"
    best = process.extractOne(query, choices, scorer=fuzz.WRatio, score_cutoff=85)
    assert best is not None
    assert best[0] == "INV-2024-001"
    assert best[1] >= 85


def test_rapidfuzz_below_cutoff_returns_none():
    """When no choice meets score_cutoff, extractOne returns None."""
    choices = ["ABC", "DEF"]
    best = process.extractOne("XYZ", choices, scorer=fuzz.WRatio, score_cutoff=90)
    assert best is None


def test_duplicate_check_result_model():
    """DuplicateCheckResult serializes correctly."""
    r = DuplicateCheckResult(
        is_duplicate=True,
        matched_job_ids=["job-1"],
        scores={"job-1": 92.5},
        content_hash_matched=True,
    )
    d = r.model_dump()
    assert d["is_duplicate"] is True
    assert d["matched_job_ids"] == ["job-1"]
    assert d["scores"]["job-1"] == 92.5
    assert d["content_hash_matched"] is True
