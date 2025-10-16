from typing import Optional, List
from pydantic import BaseModel, EmailStr, Field


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=200)
    phone: Optional[str] = Field(None, min_length=5, max_length=30)
    locale: Optional[str] = Field(None, min_length=2, max_length=20)
    time_zone: Optional[str] = Field(None, min_length=1, max_length=50)


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    full_name: Optional[str] = None
    phone: Optional[str] = None
    locale: Optional[str] = None
    time_zone: Optional[str] = None
    avatar_url: Optional[str] = None
    roles: List[str] = []
    permissions: List[str] = []


class PreferencesUpdateRequest(BaseModel):
    theme: Optional[str] = Field(None, pattern=r"^(light|dark|system)$")
    density: Optional[str] = Field(None, pattern=r"^(comfortable|compact)$")
    locale: Optional[str] = None
    time_zone: Optional[str] = None
    notifications_email: Optional[bool] = None
    notifications_push: Optional[bool] = None


class PreferencesResponse(BaseModel):
    theme: str
    density: str
    locale: Optional[str] = None
    time_zone: Optional[str] = None
    notifications_email: bool
    notifications_push: bool


class AvatarUploadResponse(BaseModel):
    avatar_url: str