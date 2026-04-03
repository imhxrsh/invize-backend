"""
Pydantic models for Operations & Workflow Agent.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class ExceptionClassification(BaseModel):
    exception_type: str  # duplicate | authenticity_concern | no_po | match_variance | processing_failed | clean
    queue_name: str
    suggested_actions: List[str] = []
    reason: str = ""  # human-readable why this classification was chosen


class ApprovalSummary(BaseModel):
    status: str  # pending | approved | rejected
    current_level: int = 1
    due_at: Optional[str] = None  # ISO datetime
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None


class OperationsWorkflowResult(BaseModel):
    exception: Optional[Dict[str, Any]] = None  # ExceptionClassification as dict
    approval_summary: Optional[Dict[str, Any]] = None  # ApprovalSummary as dict
    review_item_id: Optional[str] = None  # DocumentReviewItem id if created
    approval_id: Optional[str] = None  # DocumentApproval id if created


# API DTOs
class QueueCountsResponse(BaseModel):
    queue_counts: Dict[str, int]
    total_pending: int


class QueueItemResponse(BaseModel):
    id: str
    job_id: str
    exception_type: str
    queue_name: str
    priority: Optional[int] = None
    status: str
    created_at: str
    resolution: Optional[str] = None


class DashboardStatsResponse(BaseModel):
    queue_counts: Dict[str, int]
    avg_cycle_time_seconds: Optional[float] = None
    pending_approvals: int
    overdue_count: int
