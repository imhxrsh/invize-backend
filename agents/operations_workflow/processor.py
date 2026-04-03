"""
Operations & Workflow processor: classify exception, create review/approval/summary records, return block.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from .config import (
    USE_OPERATIONS_WORKFLOW_AGENT,
    APPROVAL_ENABLED,
    DEFAULT_SLA_HOURS,
)
from .classification import classify_exception, get_priority_for_exception
from .models import OperationsWorkflowResult

logger = logging.getLogger(__name__)

_prisma = None


def _get_prisma():
    global _prisma
    if _prisma is None:
        try:
            from db.prisma import prisma
            _prisma = prisma
        except Exception:
            pass
    return _prisma


async def run_operations_workflow(
    job_id: str,
    result: Dict[str, Any],
    *,
    org_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run operations workflow: classify exception, optionally create DocumentReviewItem,
    DocumentApproval, JobSummary; return operations_workflow block to merge into result.
    """
    if not USE_OPERATIONS_WORKFLOW_AGENT:
        return {}

    classification = classify_exception(result)
    queue_name = classification.queue_name
    priority = get_priority_for_exception(classification.exception_type)

    out = {
        "exception": classification.model_dump(),
        "approval_summary": None,
        "review_item_id": None,
        "approval_id": None,
    }

    prisma = _get_prisma()
    if prisma is None:
        logger.warning("Prisma not available; operations workflow state not persisted")
        return out

    try:
        # Upsert JobSummary (one per job when result is saved)
        status = (result.get("status") or "completed").lower()
        processing_time = result.get("processing_time")
        processing_time_seconds = float(processing_time) if processing_time is not None else None
        await prisma.jobsummary.upsert(
            where={"jobId": job_id},
            data={
                "create": {
                    "jobId": job_id,
                    "status": status,
                    "processingTimeSeconds": processing_time_seconds,
                },
                "update": {
                    "status": status,
                    "processingTimeSeconds": processing_time_seconds,
                },
            },
        )

        # Create DocumentReviewItem (one pending per job: dedupe)
        existing = await prisma.documentreviewitem.find_first(
            where={"jobId": job_id, "status": "pending"},
        )
        if existing:
            review_item = existing
        else:
            review_item = await prisma.documentreviewitem.create(
                data={
                    "jobId": job_id,
                    "exceptionType": classification.exception_type,
                    "queueName": queue_name,
                    "priority": priority,
                    "status": "pending",
                    "orgId": org_id,
                },
            )
        out["review_item_id"] = review_item.id

        # Optionally create DocumentApproval
        if APPROVAL_ENABLED:
            due_at = datetime.now(timezone.utc) + timedelta(hours=DEFAULT_SLA_HOURS)
            approval = await prisma.documentapproval.create(
                data={
                    "jobId": job_id,
                    "currentLevel": 1,
                    "status": "pending",
                    "dueAt": due_at,
                    "orgId": org_id,
                },
            )
            out["approval_id"] = approval.id
            out["approval_summary"] = {
                "status": "pending",
                "current_level": 1,
                "due_at": due_at.isoformat(),
                "approved_by": None,
                "approved_at": None,
            }
    except Exception as e:
        logger.exception("Operations workflow DB write failed for job %s: %s", job_id, e)
        # Still return classification in output
    return out
