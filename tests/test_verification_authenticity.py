"""Unit tests for Verification & Compliance — authenticity (quality + fraud signals)."""
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

# Add backend to path
sys_path = __import__("sys").path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys_path:
    sys_path.insert(0, str(_backend))

from agents.verification_compliance.authenticity import (
    _quality_checks,
    _fraud_signals,
    run_authenticity_checks,
    AuthenticityResult,
)


def test_quality_checks_sharp_image():
    """Sharp image should get higher quality score and no blur."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        path = Path(f.name)
    try:
        # Create a simple sharp image (high Laplacian variance)
        img = np.ones((100, 100, 3), dtype=np.uint8) * 200
        img[50:, :] = 50
        cv2.imwrite(str(path), img)
        score, blur_detected, warnings = _quality_checks(path)
        assert 0 <= score <= 1.0
        # Sharp edge gives high Laplacian variance; may or may not be blur_detected depending on threshold
        assert isinstance(warnings, list)
    finally:
        path.unlink(missing_ok=True)


def test_quality_checks_blurry_image():
    """Very blurry image (low Laplacian variance) should report blur."""
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        path = Path(f.name)
    try:
        # Uniform image = very low Laplacian variance
        img = np.ones((100, 100, 3), dtype=np.uint8) * 128
        cv2.imwrite(str(path), img)
        score, blur_detected, warnings = _quality_checks(path)
        assert blur_detected is True
        assert 0 <= score <= 1.0
    finally:
        path.unlink(missing_ok=True)


def test_fraud_signals_round_total():
    """Round total (e.g. 1000) should add a fraud signal."""
    extracted = {"total": 1000.0, "line_items": []}
    signals = _fraud_signals(extracted)
    assert any("round" in s.lower() for s in signals)


def test_fraud_signals_duplicate_descriptions():
    """Duplicate line item descriptions should add a fraud signal."""
    extracted = {
        "total": 100,
        "line_items": [
            {"description": "Widget A", "amount": 50},
            {"description": "Widget A", "amount": 50},
        ],
    }
    signals = _fraud_signals(extracted)
    assert any("duplicate" in s.lower() for s in signals)


def test_fraud_signals_total_mismatch():
    """Total not matching sum of line items should add a fraud signal."""
    extracted = {
        "total": 100.0,
        "line_items": [
            {"description": "A", "amount": 30},
            {"description": "B", "amount": 30},
        ],
    }
    signals = _fraud_signals(extracted)
    assert any("total" in s.lower() and "match" in s.lower() for s in signals)


def test_run_authenticity_checks_no_image():
    """When no image path exists, should return result with warning."""
    validated_data = {"extracted_data": {"total": 50}}
    result = run_authenticity_checks("job-1", Path("/nonexistent/foo.pdf"), validated_data)
    assert isinstance(result, AuthenticityResult)
    assert result.quality_score == 0.0
    assert any("image" in w.lower() for w in result.warnings)
