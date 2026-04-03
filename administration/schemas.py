from typing import List, Optional, Any, Dict
from datetime import datetime
from pydantic import BaseModel, EmailStr


class AdminUserResponse(BaseModel):
    id: str
    email: str
    full_name: Optional[str] = None
    roles: List[str] = []
    permissions: List[str] = []
    is_active: bool = True
    is_verified: bool = False
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    avatar_url: Optional[str] = None
    org_id: Optional[str] = None


class AdminUpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    roles: Optional[List[str]] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None


class AdminInviteUserRequest(BaseModel):
    email: str
    full_name: Optional[str] = None
    roles: Optional[List[str]] = None


class AdminInviteUserResponse(BaseModel):
    id: str
    email: str
    message: str


class SystemSetting(BaseModel):
    key: str
    value: str
    description: Optional[str] = None
    updated_at: Optional[datetime] = None


class SystemSettingsResponse(BaseModel):
    settings: List[SystemSetting]


class UpdateSettingRequest(BaseModel):
    value: str


class BulkUpdateSettingsRequest(BaseModel):
    settings: Dict[str, str]


class AuditLogEntry(BaseModel):
    id: str
    job_id: Optional[str] = None
    stage: Optional[str] = None
    action: str
    details: Optional[str] = None
    created_at: datetime


class AuditLogResponse(BaseModel):
    entries: List[AuditLogEntry]
    total: int


class AdminStatsResponse(BaseModel):
    total_users: int
    active_users: int
    inactive_users: int
    verified_users: int
    total_security_events: int
