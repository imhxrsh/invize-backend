"""
Pydantic models for Verification & Compliance Agent.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class DuplicateCheckResult(BaseModel):
    is_duplicate: bool = False
    matched_job_ids: List[str] = []
    scores: Dict[str, float] = {}
    content_hash_matched: bool = False


class AuthenticityResult(BaseModel):
    quality_score: float = 0.0
    blur_detected: bool = False
    warnings: List[str] = []
    fraud_signals: List[str] = []
    stamp_detection: Optional[Dict[str, Any]] = None  # Phase 2 placeholder


class VerificationComplianceResult(BaseModel):
    duplicate_check: Optional[DuplicateCheckResult] = None
    authenticity: Optional[AuthenticityResult] = None
    audit_event_ids: List[str] = []
