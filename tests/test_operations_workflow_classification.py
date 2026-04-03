"""Unit tests for Operations & Workflow exception classification."""
import os
import sys
from pathlib import Path

import pytest

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

os.environ.setdefault("USE_OPERATIONS_WORKFLOW_AGENT", "true")


def test_classify_duplicate():
    """Duplicate check is_duplicate true -> exception_type duplicate."""
    from agents.operations_workflow.classification import classify_exception

    result = {
        "status": "completed",
        "verification_compliance": {
            "duplicate_check": {"is_duplicate": True},
            "authenticity": {"warnings": [], "fraud_signals": []},
        },
        "matching_erp": {"match_result": {"match_status": "matched"}},
    }
    c = classify_exception(result)
    assert c.exception_type == "duplicate"
    assert c.queue_name == "duplicate_review"
    assert "review_duplicate" in c.suggested_actions or len(c.suggested_actions) >= 1


def test_classify_authenticity_concern():
    """Authenticity warnings or fraud_signals -> authenticity_concern."""
    from agents.operations_workflow.classification import classify_exception

    result = {
        "status": "completed",
        "verification_compliance": {
            "duplicate_check": {"is_duplicate": False},
            "authenticity": {"warnings": ["Low contrast"], "fraud_signals": []},
        },
        "matching_erp": {},
    }
    c = classify_exception(result)
    assert c.exception_type == "authenticity_concern"
    assert c.queue_name == "authenticity_review"

    result2 = {
        "status": "completed",
        "verification_compliance": {
            "duplicate_check": {"is_duplicate": False},
            "authenticity": {"warnings": [], "fraud_signals": ["Mismatch"]},
        },
        "matching_erp": {},
    }
    c2 = classify_exception(result2)
    assert c2.exception_type == "authenticity_concern"


def test_classify_no_po():
    """match_status no_po -> no_po."""
    from agents.operations_workflow.classification import classify_exception

    result = {
        "status": "completed",
        "verification_compliance": {"duplicate_check": {"is_duplicate": False}, "authenticity": {}},
        "matching_erp": {"match_result": {"match_status": "no_po"}},
    }
    c = classify_exception(result)
    assert c.exception_type == "no_po"
    assert c.queue_name == "no_po_review"
    assert "create_po" in c.suggested_actions or "approve_without_po" in c.suggested_actions


def test_classify_match_variance():
    """match_status variance -> match_variance."""
    from agents.operations_workflow.classification import classify_exception

    result = {
        "status": "completed",
        "verification_compliance": {"duplicate_check": {"is_duplicate": False}, "authenticity": {}},
        "matching_erp": {"match_result": {"match_status": "variance", "variances": []}},
    }
    c = classify_exception(result)
    assert c.exception_type == "match_variance"
    assert c.queue_name == "variance_review"


def test_classify_processing_failed():
    """status failed -> processing_failed."""
    from agents.operations_workflow.classification import classify_exception

    result = {"status": "failed", "verification_compliance": {}, "matching_erp": {}}
    c = classify_exception(result)
    assert c.exception_type == "processing_failed"
    assert c.queue_name == "failed_review"


def test_classify_clean():
    """No exceptions -> clean."""
    from agents.operations_workflow.classification import classify_exception

    result = {
        "status": "completed",
        "verification_compliance": {
            "duplicate_check": {"is_duplicate": False},
            "authenticity": {"warnings": [], "fraud_signals": []},
        },
        "matching_erp": {"match_result": {"match_status": "matched"}},
    }
    c = classify_exception(result)
    assert c.exception_type == "clean"
    assert c.queue_name == "clean"


def test_get_priority():
    """Priority ordering: processing_failed > no_po > match_variance > duplicate > authenticity > clean."""
    from agents.operations_workflow.classification import get_priority_for_exception

    assert get_priority_for_exception("processing_failed") > get_priority_for_exception("no_po")
    assert get_priority_for_exception("no_po") > get_priority_for_exception("match_variance")
    assert get_priority_for_exception("clean") == 0
