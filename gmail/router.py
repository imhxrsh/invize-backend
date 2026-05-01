"""Gmail OAuth, scan, and classification API."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote, urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from auth.dependencies import get_current_user
from config.auth_settings import AuthSettings
from config.gmail_settings import GmailSettings
from db.prisma import prisma
from gmail.client import flow_from_settings
from gmail.oauth_state import create_gmail_oauth_state, verify_gmail_oauth_state
from gmail.schemas import (
    GmailDisconnectResponse,
    GmailOAuthStartResponse,
    GmailScanDetailResponse,
    GmailScanQueuedResponse,
    GmailScannedListResponse,
    GmailScanResultItem,
    GmailStatusResponse,
)
from gmail.service import (
    disconnect_gmail,
    get_scan_row,
    get_status,
    save_connection_from_flow,
    schedule_scan_background,
)

logger = logging.getLogger("invize-backend")

router = APIRouter(prefix="/gmail", tags=["Gmail"])


def _gs() -> GmailSettings:
    return GmailSettings()


def _require_gmail_config(gs: GmailSettings) -> None:
    if not gs.GMAIL_OAUTH_CLIENT_ID or not gs.GMAIL_OAUTH_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail OAuth is not configured (GMAIL_OAUTH_CLIENT_ID / SECRET)",
        )


def _row_to_item(r: Any) -> GmailScanResultItem:
    att = r.attachmentMeta
    if att is not None and not isinstance(att, list):
        att = None
    reasons = r.reasons
    if reasons is not None and not isinstance(reasons, list):
        reasons = None
    logs = r.ingestLog
    if logs is not None and not isinstance(logs, list):
        logs = None
    return GmailScanResultItem(
        id=r.id,
        gmail_message_id=r.gmailMessageId,
        thread_id=r.threadId,
        subject=r.subject,
        from_addr=r.fromAddr,
        snippet=r.snippet,
        category=r.category,
        confidence=r.confidence,
        reasons=[str(x) for x in reasons] if reasons else None,
        attachment_meta=att,
        document_job_id=r.documentJobId,
        pipeline_status=r.pipelineStatus,
        pipeline_error=r.pipelineError,
        ingest_log=logs,
        classified_at=r.classifiedAt,
    )


@router.get("/status", response_model=GmailStatusResponse)
async def gmail_status(user=Depends(get_current_user)):
    s = await get_status(user.id)
    return GmailStatusResponse(
        connected=s["connected"],
        google_email=s.get("google_email"),
        last_sync_at=s.get("last_sync_at"),
    )


@router.get("/oauth/start", response_model=GmailOAuthStartResponse)
async def gmail_oauth_start(user=Depends(get_current_user)):
    gs = _gs()
    _require_gmail_config(gs)
    auth = AuthSettings()
    state = create_gmail_oauth_state(user.id, auth)
    flow = flow_from_settings(gs)
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
        state=state,
    )
    return GmailOAuthStartResponse(authorization_url=authorization_url)


@router.get("/oauth/callback")
async def gmail_oauth_callback(request: Request):
    gs = _gs()
    auth = AuthSettings()
    err_base = gs.GMAIL_OAUTH_FRONTEND_SUCCESS_URL.split("?")[0]

    def redirect_err(msg: str) -> RedirectResponse:
        q = urlencode({"tab": "integrations", "gmail": "error", "message": msg[:200]})
        return RedirectResponse(url=f"{err_base}?{q}", status_code=302)

    state = request.query_params.get("state")
    if not request.query_params.get("code") or not state:
        return redirect_err("missing_code_or_state")

    try:
        user_id = verify_gmail_oauth_state(state, auth)
    except Exception as e:
        logger.warning("Gmail OAuth state invalid: %s", e)
        return redirect_err("invalid_state")

    _require_gmail_config(gs)
    try:
        flow = flow_from_settings(gs)
        flow.fetch_token(authorization_response=str(request.url))
        await save_connection_from_flow(user_id=user_id, flow=flow, auth=auth, gs=gs)
    except Exception as e:
        logger.exception("Gmail OAuth token exchange failed: %s", e)
        return redirect_err(quote(str(e), safe=""))

    return RedirectResponse(url=gs.GMAIL_OAUTH_FRONTEND_SUCCESS_URL, status_code=302)


@router.post("/disconnect", response_model=GmailDisconnectResponse)
async def gmail_disconnect(user=Depends(get_current_user)):
    ok = await disconnect_gmail(user.id)
    return GmailDisconnectResponse(disconnected=ok)


@router.post("/scan", response_model=GmailScanQueuedResponse)
async def gmail_scan(request: Request, background_tasks: BackgroundTasks, user=Depends(get_current_user)):
    conn = await prisma.gmailconnection.find_unique(where={"userId": user.id})
    if not conn:
        raise HTTPException(status_code=400, detail="Gmail not connected")

    swarms_ok = bool(getattr(request.app.state, "swarms_ok", False))
    background_tasks.add_task(schedule_scan_background, str(user.id), swarms_ok)
    return GmailScanQueuedResponse(queued=True, message="Scan started in background.")


@router.get("/scanned", response_model=GmailScannedListResponse)
async def gmail_scanned(
    user=Depends(get_current_user),
    limit: int = 50,
    skip: int = 0,
    category: Optional[str] = None,
):
    where: dict = {"userId": user.id}
    if category:
        where["category"] = category

    rows = await prisma.gmailscanresult.find_many(
        where=where,
        order=[{"classifiedAt": "desc"}],
        take=min(max(limit, 1), 200),
        skip=max(skip, 0),
    )
    total = await prisma.gmailscanresult.count(where=where)

    items = [_row_to_item(r) for r in rows]
    return GmailScannedListResponse(items=items, total=total)


@router.get("/scanned/{scan_id}", response_model=GmailScanDetailResponse)
async def gmail_scanned_one(scan_id: str, user=Depends(get_current_user)):
    row = await get_scan_row(user.id, scan_id)
    if not row:
        raise HTTPException(status_code=404, detail="Scan result not found")
    return GmailScanDetailResponse(item=_row_to_item(row))
