"""Signed OAuth state JWT ties Google callback to Invize user (no cookie on API origin)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from config.auth_settings import AuthSettings


def create_gmail_oauth_state(user_id: str, settings: AuthSettings) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "typ": "gmail_oauth",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_gmail_oauth_state(token: str, settings: AuthSettings) -> str:
    payload = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_aud": False},
    )
    if payload.get("typ") != "gmail_oauth":
        raise jwt.InvalidTokenError("invalid state type")
    uid = payload.get("sub")
    if not uid:
        raise jwt.InvalidTokenError("missing sub")
    return str(uid)
