from datetime import datetime, timedelta, timezone
import secrets
from typing import List

import jwt
from passlib.context import CryptContext

from config.auth_settings import AuthSettings


pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],  # default to pbkdf2; still verify existing bcrypt hashes
    deprecated="auto",
)
settings = AuthSettings()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user_id: str, token_version: int, roles: List[str] | None = None) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN)
    payload = {
        "sub": user_id,
        "ver": token_version,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "roles": roles or [],
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    return pwd_context.hash(token)


def verify_refresh_token(token: str, token_hash: str) -> bool:
    return pwd_context.verify(token, token_hash)