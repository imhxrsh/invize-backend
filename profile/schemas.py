from typing import List, Optional
from pydantic import BaseModel, EmailStr
from datetime import datetime


class OrgView(BaseModel):
    id: str
    name: str
    logo_url: Optional[str] = None
    domains: List[str] = []


class PreferencesView(BaseModel):
    theme: str = "system"  # light | dark | system
    density: str = "comfortable"  # comfortable | compact
    locale: Optional[str] = None
    time_zone: Optional[str] = None
    notifications_email: bool = True
    notifications_push: bool = False


class SecurityEvent(BaseModel):
    type: str
    message: Optional[str] = None
    created_at: datetime


class SecuritySummary(BaseModel):
    password_last_changed_at: Optional[datetime] = None
    recent_events: List[SecurityEvent] = []


class FeatureFlags(BaseModel):
    document_intelligence_enabled: bool = True
    beta_ui: bool = False


class UnreadCounts(BaseModel):
    notifications: int = 0
    messages: int = 0


class UserView(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    phone: Optional[str] = None
    locale: Optional[str] = None
    time_zone: Optional[str] = None
    avatar_url: Optional[str] = None
    roles: List[str] = []
    permissions: List[str] = []


class ProfileContext(BaseModel):
    user: UserView
    org: Optional[OrgView] = None
    preferences: PreferencesView
    security: SecuritySummary
    feature_flags: FeatureFlags
    unread_counts: UnreadCounts