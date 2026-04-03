"""Tests for Operations & Workflow processor (run_operations_workflow)."""
import os
import sys
from pathlib import Path

import pytest

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

os.environ.setdefault("USE_OPERATIONS_WORKFLOW_AGENT", "true")
os.environ.setdefault("APPROVAL_ENABLED", "true")


@pytest.mark.asyncio
async def test_run_operations_workflow_returns_dict():
    """run_operations_workflow returns dict with exception, optional approval_summary, ids."""
    from agents.operations_workflow.processor import run_operations_workflow

    result = {
        "job_id": "test-job-ops-1",
        "status": "completed",
        "processing_time": 1.5,
        "verification_compliance": {
            "duplicate_check": {"is_duplicate": False},
            "authenticity": {"warnings": [], "fraud_signals": []},
        },
        "matching_erp": {"match_result": {"match_status": "no_po"}},
    }
    out = await run_operations_workflow("test-job-ops-1", result)
    assert isinstance(out, dict)
    assert "exception" in out
    assert out["exception"]["exception_type"] == "no_po"
    assert out["exception"]["queue_name"] == "no_po_review"
    # When Prisma is available, review_item_id and possibly approval_id are set
    # When not, they remain None but exception is still present
    assert "review_item_id" in out
    assert "approval_summary" in out or "approval_id" in out
