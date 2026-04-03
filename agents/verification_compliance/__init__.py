"""
Verification & Compliance Agent — Agent 3.
Duplicate detection, authenticity (quality + fraud signals), audit trail.
"""

from .processor import run_verification
from .models import (
    VerificationComplianceResult as VerificationResult,
    DuplicateCheckResult,
    AuthenticityResult,
)

__all__ = [
    "run_verification",
    "VerificationResult",
    "DuplicateCheckResult",
    "AuthenticityResult",
]
