from typing import List, Optional, Any, Dict
from prisma import Prisma
import secrets
from auth.security import hash_password


async def list_all_users(prisma: Prisma, org_id: Optional[str] = None) -> List[Any]:
    """List all users, optionally scoped to an org."""
    where: Dict[str, Any] = {}
    if org_id:
        where["orgId"] = org_id
    users = await prisma.user.find_many(
        where=where,
        order=[{"createdAt": "desc"}],
    )
    return users


async def admin_update_user(
    prisma: Prisma,
    user_id: str,
    full_name: Optional[str] = None,
    roles: Optional[List[str]] = None,
    permissions: Optional[List[str]] = None,
    is_active: Optional[bool] = None,
) -> Any:
    """Admin update of any user's properties."""
    data: Dict[str, Any] = {}
    if full_name is not None:
        data["fullName"] = full_name
    if roles is not None:
        data["roles"] = roles
    if permissions is not None:
        data["permissions"] = permissions
    if is_active is not None:
        data["isActive"] = is_active

    if not data:
        return await prisma.user.find_unique(where={"id": user_id})

    return await prisma.user.update(where={"id": user_id}, data=data)


async def admin_deactivate_user(prisma: Prisma, user_id: str) -> Any:
    """Deactivate a user account (soft-delete)."""
    return await prisma.user.update(
        where={"id": user_id},
        data={"isActive": False},
    )


async def admin_invite_user(
    prisma: Prisma,
    org_id: Optional[str],
    email: str,
    full_name: Optional[str] = None,
    roles: Optional[List[str]] = None,
) -> Any:
    """Create a new user in the org with a random password."""
    existing = await prisma.user.find_unique(where={"email": email})
    if existing:
        raise ValueError("Email already registered")
    password = secrets.token_urlsafe(16)
    user = await prisma.user.create(
        data={
            "email": email,
            "passwordHash": hash_password(password),
            "isActive": True,
            "isVerified": False,
            "fullName": full_name,
            "roles": roles or [],
            "permissions": [],
            "tokenVersion": 0,
            "orgId": org_id,
        },
    )
    return user


async def get_system_settings(prisma: Prisma) -> List[Any]:
    """Retrieve all system settings from IntegrationConfig table."""
    settings = await prisma.integrationconfig.find_many(
        order=[{"key": "asc"}],
    )
    return settings


async def upsert_system_setting(prisma: Prisma, key: str, value: str) -> Any:
    """Create or update a system setting by key."""
    existing = await prisma.integrationconfig.find_unique(where={"key": key})
    if existing:
        return await prisma.integrationconfig.update(
            where={"key": key},
            data={"value": value},
        )
    else:
        return await prisma.integrationconfig.create(
            data={"key": key, "value": value},
        )


async def bulk_upsert_settings(prisma: Prisma, settings: Dict[str, str]) -> List[Any]:
    """Upsert multiple settings at once."""
    results = []
    for key, value in settings.items():
        setting = await upsert_system_setting(prisma, key, value)
        results.append(setting)
    return results


async def get_audit_log(
    prisma: Prisma,
    limit: int = 50,
    skip: int = 0,
    job_id: Optional[str] = None,
) -> tuple[List[Any], int]:
    """Get audit log entries with optional filtering."""
    where: Dict[str, Any] = {}
    if job_id:
        where["jobId"] = job_id

    entries = await prisma.documentauditevent.find_many(
        where=where,
        order=[{"createdAt": "desc"}],
        take=limit,
        skip=skip,
    )
    total = await prisma.documentauditevent.count(where=where)
    return entries, total


async def get_admin_stats(prisma: Prisma, org_id: Optional[str] = None) -> Dict[str, int]:
    """Get aggregated admin stats."""
    where: Dict[str, Any] = {}
    if org_id:
        where["orgId"] = org_id

    total = await prisma.user.count(where=where)
    active = await prisma.user.count(where={**where, "isActive": True})
    inactive = await prisma.user.count(where={**where, "isActive": False})
    verified = await prisma.user.count(where={**where, "isVerified": True})
    security_events = await prisma.securityevent.count()

    return {
        "total_users": total,
        "active_users": active,
        "inactive_users": inactive,
        "verified_users": verified,
        "total_security_events": security_events,
    }
