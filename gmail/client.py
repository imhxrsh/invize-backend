"""Build Gmail API client from stored credentials."""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config.auth_settings import AuthSettings
from config.gmail_settings import GmailSettings
from db.prisma import prisma
from gmail.crypto import decrypt_token, encrypt_token

# Must match what Google returns on token exchange. Web clients often get openid + userinfo
# with gmail.readonly; if Flow scopes are narrower, oauthlib raises "Scope has changed".
SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _client_config(gs: GmailSettings) -> dict:
    return {
        "web": {
            "client_id": gs.GMAIL_OAUTH_CLIENT_ID,
            "client_secret": gs.GMAIL_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [gs.GMAIL_OAUTH_REDIRECT_URI],
        }
    }


def flow_from_settings(gs: GmailSettings):
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(_client_config(gs), scopes=SCOPES, redirect_uri=gs.GMAIL_OAUTH_REDIRECT_URI)


async def credentials_for_user(user_id: str, auth: AuthSettings, gs: GmailSettings) -> Tuple[Credentials, Any]:
    """Load Credentials for user; refresh if needed; persist new access token when refreshed."""
    row = await prisma.gmailconnection.find_unique(where={"userId": user_id})
    if not row:
        raise ValueError("Gmail not connected")

    refresh = decrypt_token(row.refreshTokenEnc, auth, gs)
    access: Optional[str] = None
    if row.accessTokenEnc:
        access = decrypt_token(row.accessTokenEnc, auth, gs)

    creds = Credentials(
        token=access,
        refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=gs.GMAIL_OAUTH_CLIENT_ID,
        client_secret=gs.GMAIL_OAUTH_CLIENT_SECRET,
        scopes=SCOPES,
    )

    updated = False

    def _refresh_if_needed() -> bool:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            return True
        return False

    if await asyncio.to_thread(_refresh_if_needed):
        updated = True

    if updated and creds.token:
        enc_access = encrypt_token(creds.token, auth, gs)
        exp = getattr(creds, "expiry", None)
        await prisma.gmailconnection.update(
            where={"userId": user_id},
            data={
                "accessTokenEnc": enc_access,
                "tokenExpiresAt": exp,
            },
        )

    def _build():
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    service = await asyncio.to_thread(_build)
    return creds, service
