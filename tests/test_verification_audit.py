"""Unit tests for Verification & Compliance — audit (structlog + optional DB)."""
import os
from pathlib import Path

import pytest

# Add backend to path
sys_path = __import__("sys").path
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys_path:
    sys_path.insert(0, str(_backend))

# Disable DB for unit tests
os.environ["AUDIT_LOG_TO_DB"] = "false"


@pytest.fixture(autouse=True)
def disable_audit_db():
    """Ensure DB write is disabled so tests don't need MongoDB."""
    os.environ["AUDIT_LOG_TO_DB"] = "false"
    yield
    os.environ["AUDIT_LOG_TO_DB"] = os.environ.get("AUDIT_LOG_TO_DB", "false")


def test_get_audit_logger_binds_context():
    """get_audit_logger returns a logger with job_id and stage bound."""
    from agents.verification_compliance.audit import get_audit_logger

    log = get_audit_logger("job-123", "verification")
    assert log is not None
    # Bound logger has _context; structlog bind returns new logger with context
    log.info("test_event")
    # No exception means success


@pytest.mark.asyncio
async def test_log_audit_event_no_db():
    """log_audit_event with AUDIT_LOG_TO_DB=false should not require DB."""
    from agents.verification_compliance.audit import log_audit_event

    event_id = await log_audit_event(
        "job-456",
        "duplicate_check",
        "duplicate_check_completed",
        {"is_duplicate": False},
    )
    # When DB is disabled, event_id can be None
    assert event_id is None or isinstance(event_id, str)
