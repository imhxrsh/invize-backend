from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from prisma import Prisma

from config.auth_settings import AuthSettings
from .security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_refresh_token,
)


settings = AuthSettings()


async def register_user(prisma: Prisma, email: str, password: str):
    existing = await prisma.user.find_unique(where={"email": email})
    if existing:
        return None, "Email already registered"
    pwd = hash_password(password)
    user = await prisma.user.create(
        data={
            "email": email,
            "passwordHash": pwd,
            "isActive": True,
            "isVerified": False,
            "roles": [],
            "permissions": [],
            "tokenVersion": 0,
        }
    )
    return user, None


async def login_user(
    prisma: Prisma, email: str, password: str, user_agent: Optional[str], ip: Optional[str]
) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    user = await prisma.user.find_unique(where={"email": email})
    if not user or not verify_password(password, user.passwordHash):
        return None, None, "Invalid credentials"

    session = await prisma.session.create(
        data={
            "userId": user.id,
            "userAgent": user_agent,
            "ip": ip,
        }
    )

    # Record successful login security event and update lastLoginAt
    try:
        await prisma.securityevent.create(
            data={
                "userId": user.id,
                "type": "login_success",
                "message": f"ua={user_agent or ''} ip={ip or ''}",
            }
        )
        await prisma.user.update(where={"id": user.id}, data={"lastLoginAt": datetime.now(timezone.utc)})
    except Exception:
        pass

    access_token = create_access_token(user_id=user.id, token_version=user.tokenVersion, roles=user.roles or [])
    raw_refresh = create_refresh_token()
    token_hash = hash_refresh_token(raw_refresh)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)

    rt = await prisma.refreshtoken.create(
        data={
            "sessionId": session.sessionId,
            "userId": user.id,
            "tokenHash": token_hash,
            "expiresAt": expires_at,
        }
    )

    composite_refresh = f"{rt.tokenId}.{raw_refresh}"
    return {"access_token": access_token}, composite_refresh, None


async def refresh_access_token(prisma: Prisma, presented_refresh: str, user_agent: Optional[str], ip: Optional[str]):
    # Expect format: <tokenId>.<raw_token>
    try:
        token_id, raw = presented_refresh.split(".", 1)
    except Exception:
        return None, None, "Malformed refresh token"

    record = await prisma.refreshtoken.find_unique(where={"tokenId": token_id})
    if not record:
        return None, None, "Refresh token not found"
    if record.revoked:
        # Token reuse attempt or manual revocation
        await prisma.session.update(
            where={"sessionId": record.sessionId},
            data={"revoked": True, "revokedAt": datetime.now(timezone.utc)},
        )
        try:
            await prisma.securityevent.create(
                data={
                    "userId": record.userId,
                    "type": "token_reuse_detected",
                    "message": "presented revoked refresh token",
                }
            )
        except Exception:
            pass
        return None, None, "Session revoked"

    # Verify token hash and expiry
    valid = verify_refresh_token(raw, record.tokenHash)
    if not valid:
        return None, None, "Invalid refresh token"
    if record.expiresAt < datetime.now(timezone.utc):
        return None, None, "Refresh token expired"

    # Load user
    user = await prisma.user.find_unique(where={"id": record.userId})
    if not user or not user.isActive:
        return None, None, "User inactive"

    # Rotate refresh token: revoke old and issue new
    new_raw = create_refresh_token()
    new_hash = hash_refresh_token(new_raw)
    new_expires = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)

    new_rt = await prisma.refreshtoken.create(
        data={
            "sessionId": record.sessionId,
            "userId": record.userId,
            "tokenHash": new_hash,
            "expiresAt": new_expires,
        }
    )

    await prisma.refreshtoken.update(
        where={"tokenId": record.tokenId},
        data={"revoked": True, "revokedAt": datetime.now(timezone.utc), "replacedByTokenId": new_rt.tokenId},
    )

    # Record refresh rotation event
    try:
        await prisma.securityevent.create(
            data={
                "userId": record.userId,
                "type": "token_refreshed",
                "message": "refresh token rotated",
            }
        )
    except Exception:
        pass

    # Issue new access token
    access = create_access_token(user_id=user.id, token_version=user.tokenVersion, roles=user.roles or [])
    new_composite = f"{new_rt.tokenId}.{new_raw}"
    return {"access_token": access}, new_composite, None


async def logout_session(prisma: Prisma, presented_refresh: Optional[str]):
    if not presented_refresh:
        # Nothing to revoke
        return
    try:
        token_id, _ = presented_refresh.split(".", 1)
    except Exception:
        return
    record = await prisma.refreshtoken.find_unique(where={"tokenId": token_id})
    if not record:
        return
    await prisma.refreshtoken.update(
        where={"tokenId": token_id},
        data={"revoked": True, "revokedAt": datetime.now(timezone.utc)},
    )
    await prisma.session.update(
        where={"sessionId": record.sessionId},
        data={"revoked": True, "revokedAt": datetime.now(timezone.utc)},
    )
    # Record logout event
    try:
        await prisma.securityevent.create(
            data={
                "userId": record.userId,
                "type": "logout",
                "message": "session closed",
            }
        )
    except Exception:
        pass