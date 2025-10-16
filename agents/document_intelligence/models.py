"""
Data models for Document Intelligence Agent
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from enum import Enum


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentType(str, Enum):
    STRUCTURED = "structured"
    SEMI_STRUCTURED = "semi_structured"
    UNSTRUCTURED = "unstructured"


class LineItem(BaseModel):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    confidence: Optional[float] = None
    item_code: Optional[str] = None
    tax_rate: Optional[float] = None
    tax_amount: Optional[float] = None


class ExtractedData(BaseModel):
    supplier: Optional[str] = None
    supplier_address: Optional[str] = None
    supplier_tax_id: Optional[str] = None
    supplier_email: Optional[str] = None
    supplier_phone: Optional[str] = None
    invoice_number: Optional[str] = None
    date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    currency_symbol: Optional[str] = None
    exchange_rate: Optional[float] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    tax_rate: Optional[float] = None
    discount: Optional[float] = None
    shipping: Optional[float] = None
    handling: Optional[float] = None
    other_charges: Optional[float] = None
    total: Optional[float] = None
    po_number: Optional[str] = None
    payment_terms: Optional[str] = None
    bill_to: Optional[str] = None
    ship_to: Optional[str] = None
    buyer: Optional[str] = None
    gstin: Optional[str] = None
    vat_id: Optional[str] = None
    pan: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc: Optional[str] = None
    iban: Optional[str] = None
    swift: Optional[str] = None
    notes: Optional[str] = None
    line_items: List[LineItem] = []
    confidence: Optional[float] = None


class DocumentUploadResponse(BaseModel):
    job_id: str
    status: DocumentStatus
    message: str


class DocumentStatusResponse(BaseModel):
    job_id: str
    status: DocumentStatus
    progress: Optional[str] = None
    error: Optional[str] = None


class DocumentResultResponse(BaseModel):
    job_id: str
    status: DocumentStatus
    document_type: Optional[DocumentType] = None
    extracted_data: Optional[ExtractedData] = None
    processing_time: Optional[float] = None
    raw_text: Optional[str] = None
    additional_fields: Optional[Dict[str, Any]] = None
    agent_analysis: Optional[Dict[str, Any]] = None
    error: Optional[str] = None