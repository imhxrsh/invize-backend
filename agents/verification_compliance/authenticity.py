"""
Authenticity: document quality (blur, contrast) and rule-based fraud signals.
Phase 1 only; stamp detection deferred (Phase 2).
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from .config import (
    AUTHENTICITY_QUALITY_ENABLED,
    AUTHENTICITY_BLUR_THRESHOLD,
    AUTHENTICITY_QUALITY_MIN_SCORE,
)
from .models import AuthenticityResult

logger = logging.getLogger(__name__)


def _get_first_page_image_path(file_path: Path, job_id: str) -> Optional[Path]:
    """Return path to first page as image for quality check."""
    if file_path.suffix.lower() == ".pdf":
        try:
            from pdf2image import convert_from_path
            base = Path(__file__).parent.parent.parent
            temp_dir = base / "agent_workspace" / "temp" / job_id
            temp_dir.mkdir(parents=True, exist_ok=True)
            pages = convert_from_path(file_path, first_page=1, last_page=1, dpi=150)
            if pages:
                first_page_path = temp_dir / "first_page_quality.jpg"
                pages[0].save(first_page_path, "JPEG")
                return first_page_path
        except Exception as e:
            logger.warning("Could not convert PDF first page for quality: %s", e)
        return None
    if file_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".tiff", ".tif"):
        return file_path
    return None


def _blur_score_gray(gray: np.ndarray) -> float:
    """Laplacian variance: lower = more blur."""
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    return float(lap.var())


def _contrast_score(gray: np.ndarray) -> float:
    """Normalized contrast (0-1) from std of pixel values."""
    std = np.std(gray)
    return min(1.0, std / 80.0) if std is not None else 0.0


def _quality_checks(image_path: Path) -> Tuple[float, bool, List[str]]:
    """
    Returns (quality_score 0-1, blur_detected, warnings).
    """
    warnings: List[str] = []
    try:
        img = cv2.imread(str(image_path))
        if img is None:
            return 0.0, True, ["Could not load image for quality check"]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        lap_var = _blur_score_gray(gray)
        blur_detected = lap_var < AUTHENTICITY_BLUR_THRESHOLD
        if blur_detected:
            warnings.append(f"Possible blur (Laplacian variance={lap_var:.1f})")
        contrast = _contrast_score(gray)
        if contrast < 0.2:
            warnings.append("Low contrast")
        # Single quality score: blend blur and contrast
        blur_component = 0.0 if blur_detected else min(1.0, lap_var / 500.0)
        quality_score = 0.6 * blur_component + 0.4 * contrast
        quality_score = max(0.0, min(1.0, quality_score))
        if quality_score < AUTHENTICITY_QUALITY_MIN_SCORE:
            warnings.append("Document quality below threshold")
        return quality_score, blur_detected, warnings
    except Exception as e:
        logger.warning("Quality check failed: %s", e)
        return 0.0, True, [str(e)]


def _fraud_signals(extracted: Dict[str, Any]) -> List[str]:
    """Rule-based fraud signals from extracted_data."""
    signals: List[str] = []
    total = extracted.get("total")
    if total is not None:
        try:
            total_f = float(total)
            if total_f == int(total_f) and total_f > 0 and total_f % 1000 == 0:
                signals.append("Round total amount (possible manual entry)")
        except (TypeError, ValueError):
            pass

    line_items = extracted.get("line_items") or []
    if len(line_items) >= 2:
        descs = []
        for item in line_items:
            d = (item.get("description") or "").strip()
            if d:
                descs.append(d)
        if len(descs) != len(set(descs)):
            signals.append("Duplicate line item descriptions")

    # Total vs sum of line items
    if total is not None and line_items:
        try:
            total_f = float(total)
            line_sum = 0.0
            for item in line_items:
                amt = item.get("amount")
                if amt is not None:
                    line_sum += float(amt)
            if abs(total_f - line_sum) > 0.02 and line_sum > 0:
                signals.append("Total does not match sum of line items")
        except (TypeError, ValueError):
            pass

    return signals


def run_authenticity_checks(
    job_id: str,
    file_path: Path,
    validated_data: Dict[str, Any],
) -> AuthenticityResult:
    """
    Run document quality and fraud-signal checks.
    Returns AuthenticityResult; stamp_detection left as None (Phase 2).
    """
    if not AUTHENTICITY_QUALITY_ENABLED:
        return AuthenticityResult()

    extracted = validated_data.get("extracted_data") or {}
    quality_score = 0.0
    blur_detected = False
    warnings: List[str] = []

    img_path = _get_first_page_image_path(file_path, job_id)
    if img_path and img_path.exists():
        quality_score, blur_detected, warnings = _quality_checks(img_path)
    else:
        warnings.append("No image available for quality check")

    fraud_signals = _fraud_signals(extracted)

    return AuthenticityResult(
        quality_score=quality_score,
        blur_detected=blur_detected,
        warnings=warnings,
        fraud_signals=fraud_signals,
        stamp_detection=None,
    )
