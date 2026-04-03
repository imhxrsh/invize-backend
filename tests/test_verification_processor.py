"""Unit and integration tests for Verification & Compliance processor."""
import os
from pathlib import Path

import pytest

# Add backend to path
sys_path = __import__("sys").path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys_path:
    sys_path.insert(0, str(_backend))

os.environ.setdefault("AUDIT_LOG_TO_DB", "false")
os.environ.setdefault("USE_VERIFICATION_AGENT", "true")


@pytest.mark.asyncio
async def test_run_verification_returns_dict():
    """run_verification returns dict with duplicate_check, authenticity, audit_event_ids."""
    from agents.verification_compliance.processor import run_verification

    validated_data = {
        "extracted_data": {
            "invoice_number": "INV-1",
            "total": 100.0,
            "date": "2024-01-01",
            "line_items": [],
        },
        "document_type": "unstructured",
        "raw_text": None,
        "additional_fields": None,
    }
    # Use a nonexistent file so duplicate_check and authenticity may skip or warn
    result = await run_verification(
        "test-job-1",
        Path("/tmp/nonexistent_file.pdf"),
        validated_data,
    )
    assert isinstance(result, dict)
    assert "duplicate_check" in result
    assert "authenticity" in result
    assert "audit_event_ids" in result
    assert isinstance(result["audit_event_ids"], list)


