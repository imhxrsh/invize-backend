from typing import List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from db.prisma import prisma
from auth.dependencies import get_current_user
from .schemas import (
    UpdateUserRequest,
    UserResponse,
    PreferencesUpdateRequest,
    PreferencesResponse,
    AvatarUploadResponse,
    TeamMemberResponse,
    InviteUserRequest,
    InviteUserResponse,
)
from .service import update_user, upsert_preferences, save_avatar, list_users_in_org, invite_user
from security.schemas import SecurityResponse, SecurityEvent
from datetime import datetime


router = APIRouter(prefix="/users", tags=["Users"])


@router.patch("/me", response_model=UserResponse)
async def patch_me(payload: UpdateUserRequest, user=Depends(get_current_user)):
    updated = await update_user(prisma, user.id, payload.model_dump(exclude_none=True))
    return UserResponse(
        id=updated.id,
        email=updated.email,
        full_name=getattr(updated, "fullName", None),
        phone=getattr(updated, "phone", None),
        locale=getattr(updated, "locale", None),
        time_zone=getattr(updated, "timeZone", None),
        avatar_url=getattr(updated, "avatarUrl", None),
        roles=updated.roles or [],
        permissions=getattr(updated, "permissions", []) or [],
    )


@router.put("/me/preferences", response_model=PreferencesResponse)
async def put_preferences(payload: PreferencesUpdateRequest, user=Depends(get_current_user)):
    prefs = await upsert_preferences(
        prisma,
        user_id=user.id,
        theme=payload.theme,
        density=payload.density,
        locale=payload.locale,
        time_zone=payload.time_zone,
        notifications_email=payload.notifications_email,
        notifications_push=payload.notifications_push,
    )
    return PreferencesResponse(
        theme=prefs.theme,
        density=prefs.density,
        locale=prefs.locale,
        time_zone=prefs.timeZone,
        notifications_email=prefs.notificationsEmail,
        notifications_push=prefs.notificationsPush,
    )


@router.post("/me/avatar", response_model=AvatarUploadResponse)
async def upload_avatar(user=Depends(get_current_user), file: UploadFile = File(...)):
    try:
        url = await save_avatar(prisma, user.id, file)
        return AvatarUploadResponse(avatar_url=url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me/security", response_model=SecurityResponse)
async def security_view(user=Depends(get_current_user)):
    # For now, return recent events if any; password_last_changed_at NA
    events = await prisma.securityevent.find_many(where={"userId": user.id})
    events_sorted = sorted(events, key=lambda e: e.createdAt, reverse=True)[:10]
    view_events = [
        SecurityEvent(type=e.type, message=getattr(e, "message", None), created_at=e.createdAt) for e in events_sorted
    ]
    return SecurityResponse(password_last_changed_at=None, recent_events=view_events)


@router.get("/team", response_model=List[TeamMemberResponse])
async def list_team(user=Depends(get_current_user)):
    """List users in the same org as the current user."""
    org_id = getattr(user, "orgId", None)
    users = await list_users_in_org(prisma, org_id)
    if not org_id:
        # No org: return only current user
        users = [user]
    return [
        TeamMemberResponse(
            id=u.id,
            email=u.email,
            full_name=getattr(u, "fullName", None),
            roles=u.roles or [],
        )
        for u in users
    ]


@router.post("/invite", response_model=InviteUserResponse)
async def invite_team_member(payload: InviteUserRequest, user=Depends(get_current_user)):
    """Create a new user in the same org. They can sign in after setting password (e.g. via forgot-password flow)."""
    org_id = getattr(user, "orgId", None)
    try:
        new_user = await invite_user(
            prisma,
            org_id=org_id,
            email=payload.email,
            full_name=payload.full_name,
            roles=payload.roles,
        )
        return InviteUserResponse(
            id=new_user.id,
            email=new_user.email,
            message="User created. They can sign in with the email; ask an admin to set a temporary password or use forgot-password when available.",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))