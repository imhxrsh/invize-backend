from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel


class SecurityEvent(BaseModel):
    type: str
    message: Optional[str] = None
    created_at: datetime


class SecurityResponse(BaseModel):
    password_last_changed_at: Optional[datetime] = None
    recent_events: List[SecurityEvent] = []