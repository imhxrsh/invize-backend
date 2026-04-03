from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.auth_settings import AuthSettings
from db.prisma import prisma

# Must match frontend ACCESS_COOKIE_NAME (lib/config.ts)
ACCESS_TOKEN_COOKIE = "invize_access_token"

# Optional bearer so we can fall back to cookie (Next.js /api rewrites forward Cookie reliably)
bearer_optional = HTTPBearer(auto_error=False)

settings = AuthSettings()


async def _user_from_jwt(token: str):
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            issuer=settings.JWT_ISSUER,
        )
        user_id = payload.get("sub")
        token_version = payload.get("ver")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    user = await prisma.user.find_unique(where={"id": user_id})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found"
        )
    if user.tokenVersion != token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token version mismatch"
        )
    return user


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_optional),
):
    """
    Resolve the current user from Authorization: Bearer or invize_access_token cookie.
    Cookie path is required when the app is used behind Next.js rewrites (/api → backend),
    because some proxy paths do not forward Authorization while Cookie is still present.
    """
    token: Optional[str] = None
    if credentials and credentials.credentials:
        token = credentials.credentials.strip()
    if not token:
        raw = request.cookies.get(ACCESS_TOKEN_COOKIE)
        if raw:
            token = raw.strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return await _user_from_jwt(token)
