"""
Configuration for Operations & Workflow Agent.
"""

import os
from dotenv import load_dotenv

load_dotenv()

USE_OPERATIONS_WORKFLOW_AGENT = os.getenv("USE_OPERATIONS_WORKFLOW_AGENT", "false").lower() == "true"
APPROVAL_ENABLED = os.getenv("APPROVAL_ENABLED", "true").lower() == "true"
DEFAULT_SLA_HOURS = float(os.getenv("DEFAULT_SLA_HOURS", "72"))
WORKFLOW_REMINDERS_ENABLED = os.getenv("WORKFLOW_REMINDERS_ENABLED", "false").lower() == "true"

# Exception type -> queue name
EXCEPTION_QUEUE_MAP = {
    "duplicate": "duplicate_review",
    "authenticity_concern": "authenticity_review",
    "no_po": "no_po_review",
    "match_variance": "variance_review",
    "processing_failed": "failed_review",
    "clean": "clean",
}
# Allow override via env: e.g. EXCEPTION_QUEUE_duplicate=duplicate_review
for key in list(EXCEPTION_QUEUE_MAP.keys()):
    env_val = os.getenv(f"EXCEPTION_QUEUE_{key}", "").strip()
    if env_val:
        EXCEPTION_QUEUE_MAP[key] = env_val

# Priority by exception type (higher = more urgent)
EXCEPTION_PRIORITY = {
    "processing_failed": 100,
    "no_po": 80,
    "match_variance": 70,
    "duplicate": 60,
    "authenticity_concern": 50,
    "clean": 0,
}
