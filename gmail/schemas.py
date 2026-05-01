from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class GmailStatusResponse(BaseModel):
    connected: bool
    google_email: Optional[str] = None
    last_sync_at: Optional[datetime] = None


class GmailOAuthStartResponse(BaseModel):
    authorization_url: str


class GmailDisconnectResponse(BaseModel):
    disconnected: bool


class GmailScanQueuedResponse(BaseModel):
    queued: bool
    message: str


class GmailScanResultItem(BaseModel):
    id: str
    gmail_message_id: str
    thread_id: Optional[str] = None
    subject: Optional[str] = None
    from_addr: Optional[str] = None
    snippet: Optional[str] = None
    category: str
    confidence: Optional[float] = None
    reasons: Optional[List[str]] = None
    attachment_meta: Optional[List[Dict[str, Any]]] = None
    document_job_id: Optional[str] = None
    pipeline_status: Optional[str] = None
    pipeline_error: Optional[str] = None
    ingest_log: Optional[List[Dict[str, Any]]] = None
    classified_at: datetime


class GmailScannedListResponse(BaseModel):
    items: List[GmailScanResultItem]
    total: int


class GmailScanDetailResponse(BaseModel):
    item: GmailScanResultItem
