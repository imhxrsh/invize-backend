"""
PO/GRN matching and variance detection.
Uses Decimal for exact monetary comparison. 2-way (invoice vs PO) and 3-way (with GRN).
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from .config import MATCH_VARIANCE_TOLERANCE_PERCENT
from .models import PODto, GRNDto, VarianceItem, MatchResult


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except Exception:
        return None


def _within_tolerance(a: Optional[Decimal], b: Optional[Decimal]) -> bool:
    if a is None or b is None:
        return a == b
    if b == 0:
        return a == 0
    pct = float(MATCH_VARIANCE_TOLERANCE_PERCENT) / 100
    return abs(float(a) - float(b)) / abs(float(b)) <= pct


def run_matching(
    extracted: Dict[str, Any],
    po: Optional[PODto],
    grns: List[GRNDto],
) -> MatchResult:
    """
    Compare invoice (extracted_data) to PO and optionally GRNs.
    Returns MatchResult with match_status, variances, tax_valid.
    """
    if po is None:
        return MatchResult(match_status="no_po", tax_valid=None)

    variances: List[VarianceItem] = []
    inv_total = _to_decimal(extracted.get("total"))
    po_total = _to_decimal(po.total)
    if inv_total is not None and po_total is not None and not _within_tolerance(inv_total, po_total):
        variances.append(
            VarianceItem(
                type="price",
                message=f"Invoice total {inv_total} does not match PO total {po_total}",
                invoice_value=float(inv_total),
                erp_value=float(po_total),
            )
        )

    inv_tax = _to_decimal(extracted.get("tax"))
    po_tax = _to_decimal(po.tax)
    tax_valid = None
    if inv_tax is not None and po_tax is not None:
        tax_valid = _within_tolerance(inv_tax, po_tax)
        if not tax_valid:
            variances.append(
                VarianceItem(
                    type="tax",
                    message=f"Invoice tax {inv_tax} does not match PO tax {po_tax}",
                    invoice_value=float(inv_tax),
                    erp_value=float(po_tax),
                )
            )

    inv_lines = extracted.get("line_items") or []
    po_lines = po.line_items or []
    for i, inv_line in enumerate(inv_lines):
        inv_qty = _to_decimal(inv_line.get("quantity"))
        inv_up = _to_decimal(inv_line.get("unit_price"))
        inv_amt = _to_decimal(inv_line.get("amount"))
        po_line = po_lines[i] if i < len(po_lines) else None
        if po_line:
            po_qty = _to_decimal(po_line.quantity)
            po_up = _to_decimal(po_line.unit_price)
            po_amt = _to_decimal(po_line.amount)
            if inv_qty is not None and po_qty is not None and not _within_tolerance(inv_qty, po_qty):
                variances.append(
                    VarianceItem(
                        type="quantity",
                        line_index=i,
                        message=f"Line {i} quantity mismatch",
                        invoice_value=float(inv_qty) if inv_qty else None,
                        erp_value=float(po_qty) if po_qty else None,
                    )
                )
            if inv_up is not None and po_up is not None and not _within_tolerance(inv_up, po_up):
                variances.append(
                    VarianceItem(
                        type="price",
                        line_index=i,
                        message=f"Line {i} unit price mismatch",
                        invoice_value=float(inv_up) if inv_up else None,
                        erp_value=float(po_up) if po_up else None,
                    )
                )

    grn_ids = [g.id for g in grns]
    if variances:
        match_status = "variance"
    else:
        match_status = "matched"

    return MatchResult(
        match_status=match_status,
        po_id=po.id,
        grn_ids=grn_ids,
        variances=variances,
        tax_valid=tax_valid,
    )
