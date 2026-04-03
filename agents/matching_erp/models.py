"""
Pydantic models for Matching & ERP Agent.
DTOs for PO, GRN, match result, vendor/GL validation, posting.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class POLineItem(BaseModel):
    item_code: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class PODto(BaseModel):
    id: str
    po_number: str
    supplier_ref: Optional[str] = None
    total: Optional[float] = None
    tax: Optional[float] = None
    line_items: List[POLineItem] = []


class GRNLineItem(BaseModel):
    item_code: Optional[str] = None
    received_quantity: Optional[float] = None
    amount: Optional[float] = None


class GRNDto(BaseModel):
    id: str
    po_id: str
    line_items: List[GRNLineItem] = []
    # Optional totals
    total_amount: Optional[float] = None


class VarianceItem(BaseModel):
    type: str  # "price" | "quantity" | "tax"
    line_index: Optional[int] = None
    message: str
    invoice_value: Optional[float] = None
    erp_value: Optional[float] = None


class MatchResult(BaseModel):
    match_status: str  # "matched" | "variance" | "no_po" | "error"
    po_id: Optional[str] = None
    grn_ids: List[str] = []
    variances: List[VarianceItem] = []
    tax_valid: Optional[bool] = None


class ValidationResult(BaseModel):
    valid: bool
    erp_id: Optional[str] = None
    reason: Optional[str] = None


class PostingResult(BaseModel):
    status: str  # "submitted" | "failed" | "skipped"
    reference: Optional[str] = None
    error: Optional[str] = None


class MatchingERPResult(BaseModel):
    match_result: Optional[Dict[str, Any]] = None
    vendor_validation: Optional[Dict[str, Any]] = None
    gl_validation: Optional[Dict[str, Any]] = None
    posting: Optional[Dict[str, Any]] = None
