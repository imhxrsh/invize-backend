"""Pytest configuration and fixtures."""
import os
import sys
from pathlib import Path

# Ensure backend root is on path
backend_root = Path(__file__).parent.parent
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

# Disable DB audit writes in tests unless explicitly testing DB
os.environ.setdefault("AUDIT_LOG_TO_DB", "false")
os.environ.setdefault("USE_VERIFICATION_AGENT", "true")
