"""
Verification & Compliance Agent — single entry point.
Calls duplicate_check, authenticity, audit; returns verification_compliance dict.
"""

import logging
from pathlib import Path
from typing import Any, Dict

from .config import (
    USE_VERIFICATION_AGENT,
    DUPLICATE_CHECK_ENABLED,
    AUTHENTICITY_QUALITY_ENABLED,
    AUDIT_LOG_ENABLED,
)
from . import audit
from .models import (
    DuplicateCheckResult,
    AuthenticityResult,
    VerificationComplianceResult,
)

logger = logging.getLogger(__name__)


async def run_verification(
    job_id: str,
    file_path: Path,
    validated_data: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Run verification and compliance steps; return block to merge into result.
    Returns a dict with keys: duplicate_check, authenticity, audit_event_ids.
    """
    if not USE_VERIFICATION_AGENT:
        return {}

    audit_event_ids = []
    duplicate_result: Dict[str, Any] = {}
    authenticity_result: Dict[str, Any] = {}

    if AUDIT_LOG_ENABLED:
        event_id = await audit.log_audit_event(
            job_id, "verification", "verification_started", {"file_path": str(file_path)}
        )
        if event_id:
            audit_event_ids.append(event_id)

    try:
        # Duplicate check
        if DUPLICATE_CHECK_ENABLED:
            from . import duplicate_check
            dup = await duplicate_check.run_duplicate_check(
                job_id=job_id,
                file_path=file_path,
                validated_data=validated_data,
            )
            duplicate_result = dup.model_dump() if dup else {}
            if AUDIT_LOG_ENABLED:
                eid = await audit.log_audit_event(
                    job_id, "duplicate_check", "duplicate_check_completed", duplicate_result
                )
                if eid:
                    audit_event_ids.append(eid)

        # Authenticity (quality + fraud signals)
        if AUTHENTICITY_QUALITY_ENABLED:
            from . import authenticity as auth_module
            auth = auth_module.run_authenticity_checks(
                job_id=job_id,
                file_path=file_path,
                validated_data=validated_data,
            )
            authenticity_result = auth.model_dump() if auth else {}
            if AUDIT_LOG_ENABLED:
                eid = await audit.log_audit_event(
                    job_id, "authenticity", "authenticity_completed", authenticity_result
                )
                if eid:
                    audit_event_ids.append(eid)

        if AUDIT_LOG_ENABLED:
            eid = await audit.log_audit_event(
                job_id,
                "verification",
                "verification_completed",
                {"audit_event_ids": audit_event_ids},
            )
            if eid:
                audit_event_ids.append(eid)

    except Exception as e:
        logger.exception("Verification failed for job %s: %s", job_id, e)
        if AUDIT_LOG_ENABLED:
            await audit.log_audit_event(
                job_id, "verification", "verification_failed", {"error": str(e)}
            )
        # Still return what we have
        pass

    return {
        "duplicate_check": duplicate_result or None,
        "authenticity": authenticity_result or None,
        "audit_event_ids": audit_event_ids,
    }
