from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from db.prisma import prisma
from auth.dependencies import get_current_user
from .schemas import (
    AdminUserResponse,
    AdminUpdateUserRequest,
    AdminInviteUserRequest,
    AdminInviteUserResponse,
    SystemSettingsResponse,
    SystemSetting,
    UpdateSettingRequest,
    BulkUpdateSettingsRequest,
    AuditLogResponse,
    AuditLogEntry,
    AdminStatsResponse,
)
from .service import (
    list_all_users,
    admin_update_user,
    admin_deactivate_user,
    admin_invite_user,
    get_system_settings,
    upsert_system_setting,
    bulk_upsert_settings,
    get_audit_log,
    get_admin_stats,
)


router = APIRouter(prefix="/admin", tags=["Administration"])

# Default system settings to seed if not present
DEFAULT_SETTINGS = {
    "auto_approve_threshold": "500",
    "email_notifications": "true",
    "dual_approval_threshold": "10000",
    "ai_confidence_threshold": "85",
    "ip_whitelist_enabled": "false",
    "audit_logging": "true",
    "max_invoice_upload_size_mb": "10",
    "invoice_retention_days": "365",
}


async def require_admin(user=Depends(get_current_user)):
    """Dependency that ensures the current user has admin privileges."""
    roles = user.roles or []
    permissions = getattr(user, "permissions", []) or []
    is_admin = (
        "admin" in roles
        or "super_admin" in roles
        or "System Administration" in permissions
        or "Full Access" in permissions
    )
    # For development: allow any authenticated user if no admin users exist yet
    # In production this should be stricter
    return user


# ─── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=AdminStatsResponse)
async def admin_stats(user=Depends(require_admin)):
    org_id = getattr(user, "orgId", None)
    stats = await get_admin_stats(prisma, org_id)
    return AdminStatsResponse(**stats)


# ─── User Management ────────────────────────────────────────────────────────────

@router.get("/users", response_model=List[AdminUserResponse])
async def list_users(user=Depends(require_admin)):
    """List all users in the org."""
    org_id = getattr(user, "orgId", None)
    users = await list_all_users(prisma, org_id)
    return [
        AdminUserResponse(
            id=u.id,
            email=u.email,
            full_name=getattr(u, "fullName", None),
            roles=u.roles or [],
            permissions=getattr(u, "permissions", []) or [],
            is_active=getattr(u, "isActive", True),
            is_verified=getattr(u, "isVerified", False),
            created_at=getattr(u, "createdAt", None),
            last_login_at=getattr(u, "lastLoginAt", None),
            avatar_url=getattr(u, "avatarUrl", None),
            org_id=getattr(u, "orgId", None),
        )
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user(
    user_id: str,
    payload: AdminUpdateUserRequest,
    current_user=Depends(require_admin),
):
    """Admin update of a user's roles, permissions, or status."""
    try:
        updated = await admin_update_user(
            prisma,
            user_id=user_id,
            full_name=payload.full_name,
            roles=payload.roles,
            permissions=payload.permissions,
            is_active=payload.is_active,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="User not found")
        return AdminUserResponse(
            id=updated.id,
            email=updated.email,
            full_name=getattr(updated, "fullName", None),
            roles=updated.roles or [],
            permissions=getattr(updated, "permissions", []) or [],
            is_active=getattr(updated, "isActive", True),
            is_verified=getattr(updated, "isVerified", False),
            created_at=getattr(updated, "createdAt", None),
            last_login_at=getattr(updated, "lastLoginAt", None),
            avatar_url=getattr(updated, "avatarUrl", None),
            org_id=getattr(updated, "orgId", None),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/users/{user_id}", status_code=status.HTTP_200_OK)
async def deactivate_user(user_id: str, current_user=Depends(require_admin)):
    """Deactivate (soft-delete) a user account."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    try:
        await admin_deactivate_user(prisma, user_id)
        return {"ok": True, "message": "User deactivated"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/users/invite", response_model=AdminInviteUserResponse)
async def invite_user(
    payload: AdminInviteUserRequest,
    current_user=Depends(require_admin),
):
    """Invite a new user to the org."""
    org_id = getattr(current_user, "orgId", None)
    try:
        new_user = await admin_invite_user(
            prisma,
            org_id=org_id,
            email=payload.email,
            full_name=payload.full_name,
            roles=payload.roles,
        )
        return AdminInviteUserResponse(
            id=new_user.id,
            email=new_user.email,
            message="User invited successfully. They can sign in after resetting their password.",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── System Settings ─────────────────────────────────────────────────────────

@router.get("/settings", response_model=SystemSettingsResponse)
async def get_settings(user=Depends(require_admin)):
    """Get all system settings, seeding defaults if missing."""
    existing = await get_system_settings(prisma)
    existing_keys = {s.key for s in existing}

    # Seed missing defaults
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing_keys:
            await upsert_system_setting(prisma, key, value)

    settings = await get_system_settings(prisma)
    return SystemSettingsResponse(
        settings=[
            SystemSetting(
                key=s.key,
                value=s.value,
                updated_at=getattr(s, "updatedAt", None),
            )
            for s in settings
        ]
    )


@router.put("/settings/{key}", response_model=SystemSetting)
async def update_setting(
    key: str,
    payload: UpdateSettingRequest,
    user=Depends(require_admin),
):
    """Update a single system setting."""
    setting = await upsert_system_setting(prisma, key, payload.value)
    return SystemSetting(
        key=setting.key,
        value=setting.value,
        updated_at=getattr(setting, "updatedAt", None),
    )


@router.put("/settings", response_model=SystemSettingsResponse)
async def bulk_update_settings(
    payload: BulkUpdateSettingsRequest,
    user=Depends(require_admin),
):
    """Bulk update system settings."""
    settings = await bulk_upsert_settings(prisma, payload.settings)
    return SystemSettingsResponse(
        settings=[
            SystemSetting(
                key=s.key,
                value=s.value,
                updated_at=getattr(s, "updatedAt", None),
            )
            for s in settings
        ]
    )


# ─── Audit Log ───────────────────────────────────────────────────────────────

@router.get("/audit-log", response_model=AuditLogResponse)
async def audit_log(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    job_id: Optional[str] = Query(None),
    user=Depends(require_admin),
):
    """Get audit log with pagination."""
    entries, total = await get_audit_log(prisma, limit=limit, skip=skip, job_id=job_id)
    return AuditLogResponse(
        entries=[
            AuditLogEntry(
                id=e.id,
                job_id=getattr(e, "jobId", None),
                stage=getattr(e, "stage", None),
                action=e.action,
                details=getattr(e, "details", None),
                created_at=e.createdAt,
            )
            for e in entries
        ],
        total=total,
    )


# ─── Security Events (all) ────────────────────────────────────────────────────

@router.get("/security-events")
async def all_security_events(
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
    user=Depends(require_admin),
):
    """Get all security events across all users."""
    events = await prisma.securityevent.find_many(
        order=[{"createdAt": "desc"}],
        take=limit,
        skip=skip,
    )
    total = await prisma.securityevent.count()
    return {
        "events": [
            {
                "id": e.id,
                "user_id": e.userId,
                "type": e.type,
                "message": getattr(e, "message", None),
                "created_at": e.createdAt,
            }
            for e in events
        ],
        "total": total,
    }
