"""
Matching & ERP Agent — single entry point.
Loads adapter, runs PO/GRN fetch, matching, optional vendor/GL validation and posting.
Returns matching_erp dict for pipeline.
"""

import logging
from typing import Any, Dict

from .config import (
    USE_MATCHING_ERP_AGENT,
    MATCHING_ENABLED,
    MATCH_3_WAY_ENABLED,
    ERP_TYPE,
    ERP_POST_INVOICE_ENABLED,
)
from . import matching
from .models import MatchingERPResult

logger = logging.getLogger(__name__)


def get_erp_adapter(erp_type: str = None):
    """Factory: return demo, rest, or stub adapter based on erp_type (or config ERP_TYPE)."""
    t = (erp_type or ERP_TYPE).lower()
    if t == "rest":
        from .adapters.rest import RestERPAdapter
        return RestERPAdapter()
    if t == "stub":
        from .adapters.stub import StubERPAdapter
        return StubERPAdapter()
    from .adapters.demo import DemoERPAdapter
    return DemoERPAdapter()


async def run_matching_erp(job_id: str, validated_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run matching and optional ERP steps; return block to merge into result.
    Returns dict with match_result, vendor_validation, gl_validation, posting.
    Uses ERP type from integrations DB if set, else env ERP_TYPE.
    """
    if not USE_MATCHING_ERP_AGENT:
        return {}

    erp_type = ERP_TYPE
    try:
        from db.prisma import prisma
        from integrations.service import get_erp_type
        erp_type = await get_erp_type(prisma)
    except Exception:
        pass

    extracted = validated_data.get("extracted_data") or {}
    po_number = (extracted.get("po_number") or "").strip()
    adapter = get_erp_adapter(erp_type)

    match_result = None
    vendor_validation = None
    posting = None

    try:
        po = await adapter.get_po(po_number)
        grns = []
        if po and MATCH_3_WAY_ENABLED:
            grns = await adapter.get_grns_for_po(po.id)

        if MATCHING_ENABLED:
            match_result = matching.run_matching(extracted, po, grns)
            match_result = match_result.model_dump()

        supplier = (extracted.get("supplier") or "").strip()
        if supplier:
            vr = adapter.validate_vendor(supplier)
            vendor_validation = vr.model_dump()

        if ERP_POST_INVOICE_ENABLED and match_result and match_result.get("match_status") == "matched":
            payload = {"extracted_data": extracted, "match_result": match_result}
            pr = adapter.post_invoice(job_id, payload)
            posting = pr.model_dump()
        elif not posting:
            posting = {"status": "skipped", "reference": None}

    except Exception as e:
        logger.exception("Matching & ERP failed for job %s: %s", job_id, e)
        match_result = {"match_status": "error", "variances": [], "grn_ids": []}
        if not match_result.get("po_id"):
            match_result["po_id"] = None
        if "tax_valid" not in match_result:
            match_result["tax_valid"] = None

    return {
        "match_result": match_result,
        "vendor_validation": vendor_validation,
        "gl_validation": None,
        "posting": posting,
    }
