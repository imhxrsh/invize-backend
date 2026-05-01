"""Encrypt/decrypt OAuth tokens at rest."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from config.auth_settings import AuthSettings
from config.gmail_settings import GmailSettings


def _fernet(auth: AuthSettings, gmail: GmailSettings) -> Fernet:
    raw = (gmail.GMAIL_TOKEN_FERNET_KEY or "").strip()
    if raw:
        return Fernet(raw.encode() if isinstance(raw, str) else raw)
    digest = hashlib.sha256(f"{auth.JWT_SECRET}|invize-gmail-fernet-v1".encode()).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_token(plaintext: str, auth: AuthSettings, gmail: GmailSettings) -> str:
    return _fernet(auth, gmail).encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str, auth: AuthSettings, gmail: GmailSettings) -> str:
    return _fernet(auth, gmail).decrypt(ciphertext.encode()).decode()
