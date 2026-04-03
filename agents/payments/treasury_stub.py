"""
Stub treasury / bank adapter. Real Razorpay, Stripe, or bank file export plugs in here later.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

logger = logging.getLogger(__name__)


class TreasuryStub:
    """No-op execution: logs and returns a fake reference."""

    def submit_batch(self, batch_id: str) -> Dict[str, Any]:
        ref = f"STUB-{uuid.uuid4().hex[:12].upper()}"
        logger.info("TreasuryStub.submit_batch batch_id=%s reference=%s", batch_id, ref)
        return {"ok": True, "reference": ref, "adapter": "stub"}
