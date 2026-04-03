"""
Stub ERP adapter: returns None/empty/skipped. For tests and no-ERP mode.
"""

from typing import List, Optional

from ..models import PODto, GRNDto, ValidationResult, PostingResult
from .base import ERPAdapterBase


class StubERPAdapter(ERPAdapterBase):
    """Returns no PO, no GRNs, validation/posting skipped. For tests."""

    async def get_po(self, po_number: str) -> Optional[PODto]:
        return None

    async def get_grns_for_po(self, po_id: str) -> List[GRNDto]:
        return []

    def validate_vendor(self, supplier_id_or_name: str) -> ValidationResult:
        return ValidationResult(valid=False, reason="stub_skipped")

    def validate_gl_code(self, gl_code: str) -> ValidationResult:
        return ValidationResult(valid=False, reason="stub_skipped")

    def post_invoice(self, job_id: str, payload: dict) -> PostingResult:
        return PostingResult(status="skipped", reference=None)
