"""
REST ERP adapter: calls configurable endpoints via httpx.AsyncClient.
For future Tally/SAP connector or external API.
"""

import logging
from typing import List, Optional

import httpx

from ..config import ERP_BASE_URL, ERP_API_KEY, ERP_AUTH_HEADER, ERP_TIMEOUT
from ..models import PODto, POLineItem, GRNDto, GRNLineItem, ValidationResult, PostingResult
from .base import ERPAdapterBase

logger = logging.getLogger(__name__)


def _headers() -> dict:
    h = {"Accept": "application/json"}
    if ERP_API_KEY:
        h["Authorization"] = f"Bearer {ERP_API_KEY}"
    if ERP_AUTH_HEADER:
        h["Authorization"] = ERP_AUTH_HEADER
    return h


class RestERPAdapter(ERPAdapterBase):
    """Calls REST API at ERP_BASE_URL. For future Tally/SAP."""

    def __init__(self):
        self._base = (ERP_BASE_URL or "").rstrip("/")
        self._timeout = max(1.0, min(ERP_TIMEOUT, 120))

    async def get_po(self, po_number: str) -> Optional[PODto]:
        if not self._base:
            return None
        url = f"{self._base}/api/po"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(url, params={"number": po_number}, headers=_headers())
                r.raise_for_status()
                raw = r.json()
        except Exception as e:
            logger.warning("REST get_po failed: %s", e)
            return None
        data = raw[0] if isinstance(raw, list) and raw else raw
        if not data:
            return None
        line_items = [
            POLineItem(
                item_code=d.get("item_code"),
                quantity=d.get("quantity"),
                unit_price=d.get("unit_price"),
                amount=d.get("amount"),
            )
            for d in data.get("line_items", [])
        ]
        return PODto(
            id=str(data.get("id", "")),
            po_number=data.get("po_number", ""),
            supplier_ref=data.get("supplier_ref"),
            total=data.get("total"),
            tax=data.get("tax"),
            line_items=line_items,
        )

    async def get_grns_for_po(self, po_id: str) -> List[GRNDto]:
        if not self._base or not po_id:
            return []
        url = f"{self._base}/api/po/{po_id}/grns"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.get(url, headers=_headers())
                r.raise_for_status()
                items = r.json()
        except Exception as e:
            logger.warning("REST get_grns_for_po failed: %s", e)
            return []
        if not isinstance(items, list):
            return []
        result = []
        for d in items:
            line_items = [
                GRNLineItem(
                    item_code=x.get("item_code"),
                    received_quantity=x.get("received_quantity"),
                    amount=x.get("amount"),
                )
                for x in d.get("line_items", [])
            ]
            result.append(
                GRNDto(
                    id=str(d.get("id", "")),
                    po_id=str(d.get("po_id", "")),
                    line_items=line_items,
                    total_amount=d.get("total_amount"),
                )
            )
        return result

    def validate_vendor(self, supplier_id_or_name: str) -> ValidationResult:
        if not self._base:
            return ValidationResult(valid=False, reason="not_configured")
        # Optional: POST to /api/vendor/validate
        return ValidationResult(valid=False, reason="not_implemented")

    def post_invoice(self, job_id: str, payload: dict) -> PostingResult:
        if not self._base:
            return PostingResult(status="skipped", reference=None)
        # Optional: POST to /api/invoice/post
        return PostingResult(status="skipped", reference=None)
