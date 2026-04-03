"""
Configuration for Verification & Compliance Agent.
Env-based flags and thresholds.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base paths (same as document_intelligence for agent_workspace)
BASE_DIR = Path(__file__).parent.parent.parent
AGENT_WORKSPACE = BASE_DIR / "agent_workspace"
AUDIT_LOG_DIR = AGENT_WORKSPACE / "audit"
AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)

# Feature flags
USE_VERIFICATION_AGENT = os.getenv("USE_VERIFICATION_AGENT", "true").lower() == "true"
DUPLICATE_CHECK_ENABLED = os.getenv("DUPLICATE_CHECK_ENABLED", "true").lower() == "true"
AUTHENTICITY_QUALITY_ENABLED = os.getenv("AUTHENTICITY_QUALITY_ENABLED", "true").lower() == "true"
AUDIT_LOG_ENABLED = os.getenv("AUDIT_LOG_ENABLED", "true").lower() == "true"
AUDIT_LOG_TO_DB = os.getenv("AUDIT_LOG_TO_DB", "true").lower() == "true"

# Duplicate detection
DUPLICATE_INVOICE_NUMBER_THRESHOLD = float(os.getenv("DUPLICATE_INVOICE_NUMBER_THRESHOLD", "85"))
DUPLICATE_HASH_MAX_DISTANCE = int(os.getenv("DUPLICATE_HASH_MAX_DISTANCE", "10"))
DUPLICATE_LOOKBACK_DAYS = int(os.getenv("DUPLICATE_LOOKBACK_DAYS", "365"))

# Authenticity / quality
AUTHENTICITY_BLUR_THRESHOLD = float(os.getenv("AUTHENTICITY_BLUR_THRESHOLD", "100"))
AUTHENTICITY_QUALITY_MIN_SCORE = float(os.getenv("AUTHENTICITY_QUALITY_MIN_SCORE", "0.3"))

# Audit
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE") or str(AUDIT_LOG_DIR / "audit.log")
