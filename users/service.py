from typing import Optional, Dict, Any, List
from fastapi import UploadFile
from prisma import Prisma
import os
import uuid
import secrets
from datetime import datetime


async def update_user(prisma: Prisma, user_id: str, data: Dict[str, Any]):
    # Map incoming keys to DB fields
    mapped: Dict[str, Any] = {}
    if "full_name" in data and data["full_name"] is not None:
        mapped["fullName"] = data["full_name"]
    if "phone" in data and data["phone"] is not None:
        mapped["phone"] = data["phone"]
    if "locale" in data and data["locale"] is not None:
        mapped["locale"] = data["locale"]
    if "time_zone" in data and data["time_zone"] is not None:
        mapped["timeZone"] = data["time_zone"]

    if not mapped:
        # No changes
        user = await prisma.user.find_unique(where={"id": user_id})
        return user

    user = await prisma.user.update(where={"id": user_id}, data=mapped)
    return user


async def upsert_preferences(
    prisma: Prisma,
    user_id: str,
    theme: Optional[str],
    density: Optional[str],
    locale: Optional[str],
    time_zone: Optional[str],
    notifications_email: Optional[bool],
    notifications_push: Optional[bool],
):
    update_data: Dict[str, Any] = {}
    create_data: Dict[str, Any] = {"userId": user_id}

    if theme is not None:
        update_data["theme"] = theme
        create_data["theme"] = theme
    if density is not None:
        update_data["density"] = density
        create_data["density"] = density
    if locale is not None:
        update_data["locale"] = locale
        create_data["locale"] = locale
    if time_zone is not None:
        update_data["timeZone"] = time_zone
        create_data["timeZone"] = time_zone
    if notifications_email is not None:
        update_data["notificationsEmail"] = notifications_email
        create_data["notificationsEmail"] = notifications_email
    if notifications_push is not None:
        update_data["notificationsPush"] = notifications_push
        create_data["notificationsPush"] = notifications_push

    prefs = await prisma.userpreferences.upsert(
        where={"userId": user_id},
        data={"update": update_data, "create": create_data},
    )
    return prefs


async def save_avatar(prisma: Prisma, user_id: str, file: UploadFile) -> str:
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise ValueError("Invalid avatar file type")

    uploads_dir = os.path.join(os.getcwd(), "uploads", "avatars")
    os.makedirs(uploads_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(uploads_dir, filename)

    # Save file
    data = await file.read()
    with open(path, "wb") as f:
        f.write(data)

    # Store relative URL (served via /uploads)
    avatar_url = f"/uploads/avatars/{filename}"
    await prisma.user.update(where={"id": user_id}, data={"avatarUrl": avatar_url})
    return avatar_url


async def list_users_in_org(prisma: Prisma, org_id: Optional[str]) -> List[Any]:
    """List users in the same org as the given org_id. If org_id is None, return current user only."""
    if not org_id:
        return []
    users = await prisma.user.find_many(
        where={"orgId": org_id},
        order=[{"createdAt": "desc"}],
    )
    return users


async def invite_user(
    prisma: Prisma,
    org_id: Optional[str],
    email: str,
    full_name: Optional[str] = None,
    roles: Optional[List[str]] = None,
) -> Any:
    """Create a new user in the org. Random password; user must use forgot-password or admin sets it."""
    from auth.security import hash_password
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