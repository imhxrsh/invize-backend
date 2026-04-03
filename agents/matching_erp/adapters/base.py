"""
Abstract base for ERP adapters.
Demo, REST (Tally/SAP later), and stub implement this interface.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from ..models import PODto, GRNDto, ValidationResult, PostingResult


class ERPAdapterBase(ABC):
    """Interface for get_po, get_grns_for_po, validate_vendor, validate_gl_code, post_invoice."""

    @abstractmethod
    async def get_po(self, po_number: str) -> Optional[PODto]:
        """Return PO by number or None if not found."""
        ...

    @abstractmethod
    async def get_grns_for_po(self, po_id: str) -> List[GRNDto]:
        """Return GRNs linked to the given PO."""
        ...

    def validate_vendor(self, supplier_id_or_name: str) -> ValidationResult:
        """Optional. Return validation result; default not implemented."""
        return ValidationResult(valid=False, reason="not_implemented")

    def validate_gl_code(self, gl_code: str) -> ValidationResult:
        """Optional. Return validation result; default not implemented."""
        return ValidationResult(valid=False, reason="not_implemented")

    def post_invoice(self, job_id: str, payload: dict) -> PostingResult:
        """Optional. Post invoice to ERP; default skipped."""
        return PostingResult(status="skipped", reference=None)
