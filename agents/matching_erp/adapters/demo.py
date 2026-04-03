"""
Demo ERP adapter: loads PO/GRN/vendor from demo_data (demo_erp.json).
For demo only; Tally and SAP connectors to be built later.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from ..config import DEMO_ERP_JSON
from ..models import PODto, POLineItem, GRNDto, GRNLineItem, ValidationResult
from .base import ERPAdapterBase

logger = logging.getLogger(__name__)

_data: Optional[dict] = None


def _load_demo_data() -> dict:
    global _data
    if _data is not None:
        return _data
    path = DEMO_ERP_JSON
    if not path.exists():
        logger.warning("Demo ERP data not found at %s", path)
        _data = {"pos": [], "grns": [], "vendors": []}
        return _data
    try:
        with open(path, "r") as f:
            _data = json.load(f)
    except Exception as e:
        logger.warning("Failed to load demo ERP data: %s", e)
        _data = {"pos": [], "grns": [], "vendors": []}
    return _data


def _normalize(s: Optional[str]) -> str:
    if s is None:
        return ""
    return " ".join(str(s).lower().split())


class DemoERPAdapter(ERPAdapterBase):
    """Reads from demo_data/demo_erp.json. No real ERP."""

    async def get_po(self, po_number: str) -> Optional[PODto]:
        if not po_number or not po_number.strip():
            return None
        data = _load_demo_data()
        query = _normalize(po_number)
        for raw in data.get("pos", []):
            if _normalize(raw.get("po_number", "")) == query:
                line_items = [
                    POLineItem(
                        item_code=p.get("item_code"),
                        quantity=p.get("quantity"),
                        unit_price=p.get("unit_price"),
                        amount=p.get("amount"),
                    )
                    for p in raw.get("line_items", [])
                ]
                return PODto(
                    id=raw.get("id", ""),
                    po_number=raw.get("po_number", ""),
                    supplier_ref=raw.get("supplier_ref"),
                    total=raw.get("total"),
                    tax=raw.get("tax"),
                    line_items=line_items,
                )
        return None

    async def get_grns_for_po(self, po_id: str) -> List[GRNDto]:
        if not po_id or not po_id.strip():
            return []
        data = _load_demo_data()
        result = []
        for raw in data.get("grns", []):
            if (raw.get("po_id") or "").strip() == po_id.strip():
                line_items = [
                    GRNLineItem(
                        item_code=p.get("item_code"),
                        received_quantity=p.get("received_quantity"),
                        amount=p.get("amount"),
                    )
                    for p in raw.get("line_items", [])
                ]
                result.append(
                    GRNDto(
                        id=raw.get("id", ""),
                        po_id=raw.get("po_id", ""),
                        line_items=line_items,
                        total_amount=raw.get("total_amount"),
                    )
                )
        return result

    def validate_vendor(self, supplier_id_or_name: str) -> ValidationResult:
        if not supplier_id_or_name or not supplier_id_or_name.strip():
            return ValidationResult(valid=False, reason="empty")
        data = _load_demo_data()
        query = _normalize(supplier_id_or_name)
        for v in data.get("vendors", []):
            if _normalize(v.get("name", "")) == query or query in _normalize(v.get("name", "")):
                if v.get("valid", True):
                    return ValidationResult(valid=True, erp_id=v.get("erp_id"))
                return ValidationResult(valid=False, reason="vendor_inactive")
        return ValidationResult(valid=False, reason="not_found")
