"""
Configuration for Matching & ERP Agent.
Env-based flags and thresholds. Demo adapter by default (Tally/SAP later).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Feature flags
USE_MATCHING_ERP_AGENT = os.getenv("USE_MATCHING_ERP_AGENT", "false").lower() == "true"
MATCHING_ENABLED = os.getenv("MATCHING_ENABLED", "true").lower() == "true"
MATCH_3_WAY_ENABLED = os.getenv("MATCH_3_WAY_ENABLED", "true").lower() == "true"
MATCH_VARIANCE_TOLERANCE_PERCENT = float(os.getenv("MATCH_VARIANCE_TOLERANCE_PERCENT", "0"))
ERP_POST_INVOICE_ENABLED = os.getenv("ERP_POST_INVOICE_ENABLED", "false").lower() == "true"

# ERP adapter type: demo | rest | stub
ERP_TYPE = os.getenv("ERP_TYPE", "demo").lower().strip() or "demo"
if ERP_TYPE not in ("demo", "rest", "stub"):
    ERP_TYPE = "demo"

# REST adapter (for future Tally/SAP)
ERP_BASE_URL = os.getenv("ERP_BASE_URL", "").strip()
ERP_API_KEY = os.getenv("ERP_API_KEY", "").strip()
ERP_AUTH_HEADER = os.getenv("ERP_AUTH_HEADER", "").strip()  # e.g. "Bearer <token>"
ERP_TIMEOUT = float(os.getenv("ERP_TIMEOUT", "30"))

# Demo data path (relative to this package)
BASE_DIR = Path(__file__).parent
DEMO_DATA_DIR = BASE_DIR / "demo_data"
DEMO_ERP_JSON = DEMO_DATA_DIR / "demo_erp.json"
