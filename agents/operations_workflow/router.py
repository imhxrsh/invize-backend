"""
FastAPI router for Operations & Workflow: queues, items, stats, approve/reject, pending approvals.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from agents.document_intelligence.config import UPLOADS_DIR
from auth.dependencies import get_current_user
from db.prisma import prisma
from .config import DEFAULT_SLA_HOURS
from .models import (
    QueueItemResponse,
    DashboardStatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflow", tags=["Operations & Workflow"])


# --- Request/response bodies ---
class UpdateItemBody(BaseModel):
    status: Optional[str] = None  # in_review | resolved
    resolution: Optional[str] = None
    assigned_to_user_id: Optional[str] = None


class ApproveRejectBody(BaseModel):
    comment: Optional[str] = None


def _read_result_json(job_id: str) -> Optional[Dict[str, Any]]:
    path = UPLOADS_DIR / f"{job_id}_result.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("Could not read result JSON for %s: %s", job_id, e)
        return None


def _write_result_json(job_id: str, data: Dict[str, Any]) -> None:
    path = UPLOADS_DIR / f"{job_id}_result.json"
    if not path.is_file():
        return
    try:
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not write result JSON for %s: %s", job_id, e)


def _parse_due_at(raw: Optional[str]) -> datetime:
    if not raw:
        return datetime.now(timezone.utc) + timedelta(hours=DEFAULT_SLA_HOURS)
    try:
        s = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.now(timezone.utc) + timedelta(hours=DEFAULT_SLA_HOURS)


def _sync_approval_summary_in_result_file(
    job_id: str,
    *,
    status: str,
    approved_at: Optional[datetime] = None,
    approved_by: Optional[str] = None,
) -> None:
    data = _read_result_json(job_id)
    if not data:
        return
    ow = data.setdefault("operations_workflow", {})
    summ = ow.setdefault("approval_summary", {})
    summ["status"] = status
    summ["approved_at"] = approved_at.isoformat() if approved_at else None
    summ["approved_by"] = approved_by
    _write_result_json(job_id, data)


async def _ensure_pending_approval(job_id: str):
    """
    Return the pending DocumentApproval for this job.

    If Mongo was reset but result.json still shows a pending approval, create a pending row
    so approve/reject match what the UI shows.
    """
    pending = await prisma.documentapproval.find_first(
        where={"jobId": job_id, "status": "pending"},
    )
    if pending:
        return pending

    data = _read_result_json(job_id)
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No pending approval found for this job",
        )
    ow = data.get("operations_workflow") or {}
    summ = ow.get("approval_summary") or {}
    if (summ.get("status") or "").lower() != "pending":
        raise HTTPException(
            status_code=404,
            detail="No pending approval found for this job",
        )

    existing = await prisma.documentapproval.find_first(where={"jobId": job_id})
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Approval already {existing.status} for this job",
        )

    due_at = _parse_due_at(summ.get("due_at"))
    level = int(summ.get("current_level") or 1)
    approval = await prisma.documentapproval.create(
        data={
            "jobId": job_id,
            "currentLevel": level,
            "status": "pending",
            "dueAt": due_at,
            "orgId": None,
        },
    )
    ow["approval_id"] = approval.id
    data["operations_workflow"] = ow
    _write_result_json(job_id, data)
    logger.info(
        "Healed missing DocumentApproval for job %s (new id %s)", job_id, approval.id
    )
    return approval


# --- Queues ---
@router.get("/queues")
async def list_queues(_user=Depends(get_current_user)):
    """List queue names and counts (pending items per queue)."""
    try:
        items = await prisma.documentreviewitem.find_many(
            where={"status": {"in": ["pending", "in_review"]}},
        )
        counts = {}
        for it in items:
            q = getattr(it, "queueName", None) or "unknown"
            counts[q] = counts.get(q, 0) + 1
        return {"queue_counts": counts, "total_pending": len(items)}
    except Exception as e:
        logger.exception("list_queues failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list queues")


@router.get("/queues/{queue_name}/items", response_model=List[QueueItemResponse])
async def list_queue_items(
    queue_name: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
):
    """List items in a queue (paginated). Sort: priority desc, createdAt asc."""
    try:
        where = {"queueName": queue_name}
        if status_filter:
            where["status"] = status_filter
        items = await prisma.documentreviewitem.find_many(
            where=where,
            order=[{"priority": "desc"}, {"createdAt": "asc"}],
            skip=offset,
            take=limit,
        )
        return [
            QueueItemResponse(
                id=it.id,
                job_id=it.jobId,
                exception_type=it.exceptionType,
                queue_name=it.queueName,
                priority=it.priority,
                status=it.status,
                created_at=it.createdAt.isoformat(),
                resolution=it.resolution,
            )
            for it in items
        ]
    except Exception as e:
        logger.exception("list_queue_items failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list queue items")


@router.patch("/items/{item_id}")
async def update_review_item(
    item_id: str, body: UpdateItemBody, _user=Depends(get_current_user)
):
    """Update review item status, resolution, or assignee."""
    try:
        data = {}
        if body.status is not None:
            data["status"] = body.status
        if body.resolution is not None:
            data["resolution"] = body.resolution
        if body.assigned_to_user_id is not None:
            data["assignedToUserId"] = body.assigned_to_user_id
        if body.status == "resolved":
            from datetime import datetime, timezone
            data["resolvedAt"] = datetime.now(timezone.utc)
        if not data:
            raise HTTPException(status_code=400, detail="No fields to update")
        item = await prisma.documentreviewitem.update(
            where={"id": item_id},
            data=data,
        )
        return {"id": item.id, "status": item.status, "resolution": item.resolution}
    except Exception as e:
        if "RecordNotFound" in type(e).__name__ or "NotFound" in str(e):
            raise HTTPException(status_code=404, detail="Item not found")
        logger.exception("update_review_item failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to update item")


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_workflow_stats(_user=Depends(get_current_user)):
    """Dashboard KPIs: queue counts, avg cycle time, pending approvals, overdue count."""
    try:
        # Queue counts (pending + in_review)
        items = await prisma.documentreviewitem.find_many(
            where={"status": {"in": ["pending", "in_review"]}},
        )
        queue_counts = {}
        for it in items:
            q = getattr(it, "queueName", None) or "unknown"
            queue_counts[q] = queue_counts.get(q, 0) + 1

        # Pending approvals and overdue
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        pending_approvals = await prisma.documentapproval.count(
            where={"status": "pending"},
        )
        overdue = await prisma.documentapproval.count(
            where={"status": "pending", "dueAt": {"lt": now}},
        )

        # Avg cycle time from JobSummary
        summaries = await prisma.jobsummary.find_many(
            where={"status": "completed", "processingTimeSeconds": {"not": None}},
        )
        avg_cycle = None
        if summaries:
            vals = [getattr(s, "processingTimeSeconds", None) for s in summaries]
            vals = [v for v in vals if v is not None]
            if vals:
                avg_cycle = sum(vals) / len(vals)

        return DashboardStatsResponse(
            queue_counts=queue_counts,
            avg_cycle_time_seconds=avg_cycle,
            pending_approvals=pending_approvals,
            overdue_count=overdue,
        )
    except Exception as e:
        logger.exception("get_workflow_stats failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get workflow stats")


@router.post("/jobs/{job_id}/approve")
async def approve_job(
    job_id: str,
    body: Optional[ApproveRejectBody] = None,
    _user=Depends(get_current_user),
):
    """Set approval status to approved for the document (job)."""
    body = body or ApproveRejectBody()
    try:
        now = datetime.now(timezone.utc)
        approval = await _ensure_pending_approval(job_id)
        await prisma.documentapproval.update(
            where={"id": approval.id},
            data={
                "status": "approved",
                "approvedAt": now,
                "approvedByUserId": _user.id,
            },
        )
        _sync_approval_summary_in_result_file(
            job_id,
            status="approved",
            approved_at=now,
            approved_by=_user.id,
        )
        return {"job_id": job_id, "status": "approved", "approved_at": now.isoformat()}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("approve_job failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to approve")


@router.post("/jobs/{job_id}/reject")
async def reject_job(
    job_id: str,
    body: Optional[ApproveRejectBody] = None,
    _user=Depends(get_current_user),
):
    """Set approval status to rejected for the document (job)."""
    try:
        approval = await _ensure_pending_approval(job_id)
        await prisma.documentapproval.update(
            where={"id": approval.id},
            data={"status": "rejected"},
        )
        _sync_approval_summary_in_result_file(
            job_id,
            status="rejected",
            approved_at=None,
            approved_by=None,
        )
        return {"job_id": job_id, "status": "rejected"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("reject_job failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to reject")


@router.get("/approvals/pending")
async def list_pending_approvals(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
):
    """List pending approvals (for current user/org or all). Sort by dueAt asc."""
    try:
        from datetime import datetime, timezone
        items = await prisma.documentapproval.find_many(
            where={"status": "pending"},
            order=[{"dueAt": "asc"}],
            skip=offset,
            take=limit,
        )
        return [
            {
                "id": a.id,
                "job_id": a.jobId,
                "current_level": a.currentLevel,
                "due_at": a.dueAt.isoformat() if a.dueAt else None,
                "created_at": a.createdAt.isoformat(),
            }
            for a in items
        ]
    except Exception as e:
        logger.exception("list_pending_approvals failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list pending approvals")
