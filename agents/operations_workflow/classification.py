"""
Exception classification from document result (verification_compliance + matching_erp).
"""

from typing import Any, Dict

from .config import EXCEPTION_QUEUE_MAP, EXCEPTION_PRIORITY
from .models import ExceptionClassification

# Static suggested resolutions per exception type (v1)
SUGGESTED_ACTIONS: Dict[str, list] = {
    "duplicate": ["review_duplicate", "override_if_false_positive"],
    "authenticity_concern": ["review_authenticity", "request_rescan", "reject"],
    "no_po": ["create_po", "approve_without_po"],
    "match_variance": ["approve_variance", "reject"],
    "processing_failed": ["retry", "manual_review", "reject"],
    "clean": [],
}


def _build_classification_reason(exc_type: str, result: Dict[str, Any]) -> str:
    """Short explanation for operators (shown in UI)."""
    vc = result.get("verification_compliance") or {}
    me = result.get("matching_erp") or {}

    if exc_type == "processing_failed":
        if (result.get("status") or "").lower() == "failed":
            return "The document pipeline failed before producing a full result."
        return "ERP matching reported an error status."

    if exc_type == "duplicate":
        dup = vc.get("duplicate_check") or {}
        mid = dup.get("matched_job_id") or dup.get("matched_invoice_number")
        return (
            "Duplicate check indicated this invoice likely matches a previously processed document"
            + (f" ({mid})." if mid else ".")
        )

    if exc_type == "authenticity_concern":
        auth = vc.get("authenticity") or {}
        parts = []
        if auth.get("warnings"):
            parts.append(f"warnings: {', '.join(str(w) for w in auth['warnings'][:3])}")
        if auth.get("fraud_signals"):
            parts.append(f"signals: {', '.join(str(s) for s in auth['fraud_signals'][:3])}")
        return "Authenticity checks raised concerns" + (f" ({'; '.join(parts)})." if parts else ".")

    if exc_type == "no_po":
        return "Purchase order could not be matched (no_po)."

    if exc_type == "match_variance":
        mr = me.get("match_result") or {}
        vars_ = mr.get("variances") or []
        return (
            "PO line match shows variances versus the invoice"
            + (f" ({len(vars_)} item(s))." if vars_ else ".")
        )

    if exc_type == "clean":
        return "No duplicate, authenticity, or PO variance rules triggered; routed as clean."

    return f"Classified as {exc_type}."


def classify_exception(result: Dict[str, Any]) -> ExceptionClassification:
    """
    Classify a completed job into an exception type from result dict.
    Uses verification_compliance and matching_erp; falls back to processing_failed if status is failed.
    """
    status = (result.get("status") or "").lower()
    if status == "failed":
        exc_type = "processing_failed"
    else:
        exc_type = _classify_from_verification_and_matching(result)

    queue_name = EXCEPTION_QUEUE_MAP.get(exc_type, exc_type)
    suggested_actions = SUGGESTED_ACTIONS.get(exc_type, [])
    reason = _build_classification_reason(exc_type, result)

    return ExceptionClassification(
        exception_type=exc_type,
        queue_name=queue_name,
        suggested_actions=suggested_actions,
        reason=reason,
    )


def _classify_from_verification_and_matching(result: Dict[str, Any]) -> str:
    vc = result.get("verification_compliance") or {}
    me = result.get("matching_erp") or {}

    # Duplicate
    dup = vc.get("duplicate_check") or {}
    if dup.get("is_duplicate") is True:
        return "duplicate"

    # Authenticity
    auth = vc.get("authenticity") or {}
    warnings = auth.get("warnings") or []
    fraud_signals = auth.get("fraud_signals") or []
    if warnings or fraud_signals:
        return "authenticity_concern"

    # Matching & ERP
    match_result = me.get("match_result") or {}
    match_status = (match_result.get("match_status") or "").lower()
    if match_status == "no_po":
        return "no_po"
    if match_status == "variance":
        return "match_variance"
    if match_status == "error":
        return "processing_failed"

    return "clean"


def get_priority_for_exception(exception_type: str) -> int:
    """Return priority (higher = more urgent) for exception type."""
    return EXCEPTION_PRIORITY.get(exception_type, 0)
