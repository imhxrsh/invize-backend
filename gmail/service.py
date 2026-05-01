"""Persist OAuth tokens and run inbox scan + optional document pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from config.auth_settings import AuthSettings
from config.gmail_settings import GmailSettings
from db.prisma import prisma
from gmail.attachments import (
    collect_fetchable_attachments,
    fetch_attachment_bytes,
    max_attachment_bytes,
    pick_processable_attachment,
)
from gmail.client import credentials_for_user
from gmail.crypto import encrypt_token
from gmail.parse import extract_from_message
from agents.email_classification import classify_email_payload

logger = logging.getLogger("invize-backend")


def _log_entry(level: str, message: str) -> dict:
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "message": (message or "")[:500],
    }


def _merge_logs(existing: Any, entries: List[dict], max_len: int = 50) -> List[dict]:
    base: List[dict] = []
    if isinstance(existing, list):
        for x in existing:
            if isinstance(x, dict):
                base.append(dict(x))
    base.extend(entries)
    return base[-max_len:]


async def save_connection_from_flow(
    *,
    user_id: str,
    flow: Any,
    auth: AuthSettings,
    gs: GmailSettings,
) -> str:
    creds = flow.credentials
    if not creds.refresh_token:
        raise ValueError("No refresh token from Google; try revoking app access and reconnect with prompt=consent")

    from googleapiclient.discovery import build

    def _read_profile() -> dict:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return service.users().getProfile(userId="me").execute()

    prof = await asyncio.to_thread(_read_profile)
    google_email = prof.get("emailAddress") or ""

    refresh_enc = encrypt_token(creds.refresh_token, auth, gs)
    access_enc: Optional[str] = None
    if creds.token:
        access_enc = encrypt_token(creds.token, auth, gs)

    await prisma.gmailconnection.upsert(
        where={"userId": user_id},
        data={
            "create": {
                "userId": user_id,
                "googleEmail": google_email,
                "refreshTokenEnc": refresh_enc,
                "accessTokenEnc": access_enc,
                "tokenExpiresAt": getattr(creds, "expiry", None),
            },
            "update": {
                "googleEmail": google_email,
                "refreshTokenEnc": refresh_enc,
                "accessTokenEnc": access_enc,
                "tokenExpiresAt": getattr(creds, "expiry", None),
            },
        },
    )
    return google_email


async def disconnect_gmail(user_id: str) -> bool:
    row = await prisma.gmailconnection.find_unique(where={"userId": user_id})
    if not row:
        return False
    await prisma.gmailconnection.delete(where={"userId": user_id})
    return True


async def get_status(user_id: str) -> dict:
    row = await prisma.gmailconnection.find_unique(where={"userId": user_id})
    if not row:
        return {"connected": False, "google_email": None, "last_sync_at": None}
    return {
        "connected": True,
        "google_email": row.googleEmail,
        "last_sync_at": row.lastSyncAt,
    }


async def _maybe_run_document_pipeline(
    *,
    user_id: str,
    gmail_message_id: str,
    msg: dict,
    service: Any,
    category: str,
    gs: GmailSettings,
) -> None:
    from agents.document_intelligence.config import UPLOADS_DIR
    from agents.document_intelligence.models import DocumentStatus
    from agents.document_intelligence.processor import DocumentProcessor

    row = await prisma.gmailscanresult.find_unique(
        where={
            "userId_gmailMessageId": {
                "userId": user_id,
                "gmailMessageId": gmail_message_id,
            }
        }
    )
    if not row:
        return

    logs: List[dict] = list(row.ingestLog) if isinstance(row.ingestLog, list) else []

    def append_logs(entries: List[dict]) -> None:
        nonlocal logs
        logs = _merge_logs(logs, entries)

    if row.pipelineStatus == "completed" and row.documentJobId:
        append_logs([_log_entry("info", "Pipeline: skipped (already completed)")])
        await prisma.gmailscanresult.update(
            where={
                "userId_gmailMessageId": {
                    "userId": user_id,
                    "gmailMessageId": gmail_message_id,
                }
            },
            data={"ingestLog": logs},
        )
        return

    if category not in gs.pipeline_category_set():
        append_logs(
            [
                _log_entry(
                    "info",
                    f"Pipeline: skipped (category '{category}' not in {sorted(gs.pipeline_category_set())})",
                )
            ]
        )
        data: dict = {"pipelineStatus": "skipped", "ingestLog": logs}
        if row.pipelineStatus != "completed":
            data["documentJobId"] = None
            data["pipelineError"] = None
        await prisma.gmailscanresult.update(
            where={
                "userId_gmailMessageId": {
                    "userId": user_id,
                    "gmailMessageId": gmail_message_id,
                }
            },
            data=data,
        )
        return

    candidates = collect_fetchable_attachments(msg)
    pick = pick_processable_attachment(candidates)
    if not pick:
        append_logs([_log_entry("warn", "Pipeline: skipped (no PDF/image attachment)")])
        data = {"pipelineStatus": "skipped", "ingestLog": logs}
        if row.pipelineStatus != "completed":
            data["documentJobId"] = None
            data["pipelineError"] = None
        await prisma.gmailscanresult.update(
            where={
                "userId_gmailMessageId": {
                    "userId": user_id,
                    "gmailMessageId": gmail_message_id,
                }
            },
            data=data,
        )
        return

    max_bytes = max_attachment_bytes(gs.GMAIL_PIPELINE_MAX_ATTACHMENT_MB)
    try:
        raw_bytes, ext = await asyncio.to_thread(
            fetch_attachment_bytes, service, gmail_message_id, pick
        )
    except Exception as e:
        logger.warning("Gmail attachment fetch failed: %s", e)
        append_logs([_log_entry("error", f"Download failed: {e}")])
        await prisma.gmailscanresult.update(
            where={
                "userId_gmailMessageId": {
                    "userId": user_id,
                    "gmailMessageId": gmail_message_id,
                }
            },
            data={
                "pipelineStatus": "failed",
                "pipelineError": str(e)[:500],
                "ingestLog": logs,
            },
        )
        return

    if len(raw_bytes) > max_bytes:
        append_logs([_log_entry("error", "Attachment exceeds size limit")])
        await prisma.gmailscanresult.update(
            where={
                "userId_gmailMessageId": {
                    "userId": user_id,
                    "gmailMessageId": gmail_message_id,
                }
            },
            data={
                "pipelineStatus": "failed",
                "pipelineError": "attachment too large",
                "ingestLog": logs,
            },
        )
        return

    job_id = str(uuid.uuid4())
    file_path = UPLOADS_DIR / f"{job_id}.{ext}"
    orig_name = pick.get("filename") or f"email-{gmail_message_id[:8]}.{ext}"

    append_logs([_log_entry("info", f"Starting document pipeline job {job_id}")])
    await prisma.gmailscanresult.update(
        where={
            "userId_gmailMessageId": {
                "userId": user_id,
                "gmailMessageId": gmail_message_id,
            }
        },
        data={
            "documentJobId": job_id,
            "pipelineStatus": "processing",
            "pipelineError": None,
            "ingestLog": logs,
        },
    )

    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "wb") as buffer:
        buffer.write(raw_bytes)

    status_file = UPLOADS_DIR / f"{job_id}_status.json"
    status_data = {
        "job_id": job_id,
        "status": DocumentStatus.PENDING.value,
        "filename": orig_name,
        "file_path": str(file_path),
    }
    with open(status_file, "w") as f:
        json.dump(status_data, f)

    processor = DocumentProcessor()
    try:
        await processor.process_document(job_id, file_path)
    except Exception as e:
        logger.exception("DocumentProcessor failed for gmail message %s", gmail_message_id)
        append_logs([_log_entry("error", f"Processor error: {e}")])
        await prisma.gmailscanresult.update(
            where={
                "userId_gmailMessageId": {
                    "userId": user_id,
                    "gmailMessageId": gmail_message_id,
                }
            },
            data={
                "pipelineStatus": "failed",
                "pipelineError": str(e)[:500],
                "ingestLog": logs,
            },
        )
        return

    final_status = "failed"
    err_msg: Optional[str] = None
    if status_file.exists():
        try:
            with open(status_file, "r") as f:
                sd = json.load(f)
            raw = (sd.get("status") or "failed").lower()
            final_status = raw if raw in ("completed", "failed") else "failed"
            err_msg = sd.get("error")
        except Exception:
            pass

    if final_status != "completed":
        append_logs([_log_entry("error", f"Pipeline finished: {final_status} {err_msg or ''}")])
        await prisma.gmailscanresult.update(
            where={
                "userId_gmailMessageId": {
                    "userId": user_id,
                    "gmailMessageId": gmail_message_id,
                }
            },
            data={
                "pipelineStatus": "failed",
                "pipelineError": (err_msg or "processing did not complete")[:500],
                "ingestLog": logs,
            },
        )
        return

    append_logs([_log_entry("info", f"Pipeline completed (job {job_id})")])
    await prisma.gmailscanresult.update(
        where={
            "userId_gmailMessageId": {
                "userId": user_id,
                "gmailMessageId": gmail_message_id,
            }
        },
        data={
            "pipelineStatus": "completed",
            "pipelineError": None,
            "ingestLog": logs,
        },
    )


async def run_gmail_scan(user_id: str, *, swarms_ok: bool) -> None:
    auth = AuthSettings()
    gs = GmailSettings()
    try:
        _, service = await credentials_for_user(user_id, auth, gs)
    except Exception as e:
        logger.exception("Gmail scan: credentials failed: %s", e)
        return

    max_n = max(1, min(100, gs.GMAIL_SCAN_MAX_MESSAGES))
    try:
        resp = await asyncio.to_thread(
            lambda: service.users().messages().list(userId="me", maxResults=max_n).execute()
        )
    except Exception as e:
        logger.exception("Gmail scan: list failed: %s", e)
        return

    mids = [m["id"] for m in resp.get("messages") or []]
    now = datetime.now(timezone.utc)

    for mid in mids:
        existing = await prisma.gmailscanresult.find_unique(
            where={"userId_gmailMessageId": {"userId": user_id, "gmailMessageId": mid}}
        )
        pre_logs = existing.ingestLog if existing else None

        try:
            msg = await asyncio.to_thread(
                lambda m=mid: service.users().messages().get(userId="me", id=m, format="full").execute()
            )
        except Exception as e:
            logger.warning("Gmail scan: get message %s: %s", mid, e)
            continue

        subject, from_addr, date, snippet, body, attachments = extract_from_message(msg)
        thread_id = msg.get("threadId")

        class_logs = [
            _log_entry("info", f"Message {mid[:16]}… fetched"),
        ]
        result = await asyncio.to_thread(
            lambda: classify_email_payload(
                subject=subject,
                from_addr=from_addr,
                date=date,
                snippet=snippet,
                body_text=body,
                attachments=attachments,
                swarms_ok=swarms_ok,
            )
        )
        category = str(result.get("category") or "unclear")
        class_logs.append(
            _log_entry(
                "info",
                f"Classified: {category} (confidence {result.get('confidence')})",
            )
        )
        reasons: Any = result.get("reasons") or []
        ingest_after_class = _merge_logs(pre_logs, class_logs)

        try:
            await prisma.gmailscanresult.upsert(
                where={
                    "userId_gmailMessageId": {
                        "userId": user_id,
                        "gmailMessageId": mid,
                    }
                },
                data={
                    "create": {
                        "userId": user_id,
                        "gmailMessageId": mid,
                        "threadId": thread_id,
                        "subject": subject or None,
                        "fromAddr": from_addr or None,
                        "snippet": snippet or None,
                        "bodyPreview": body or None,
                        "attachmentMeta": attachments,
                        "category": category,
                        "confidence": result.get("confidence"),
                        "reasons": reasons,
                        "rawAgentResult": (result.get("raw_agent_result") or None),
                        "ingestLog": ingest_after_class,
                    },
                    "update": {
                        "threadId": thread_id,
                        "subject": subject or None,
                        "fromAddr": from_addr or None,
                        "snippet": snippet or None,
                        "bodyPreview": body or None,
                        "attachmentMeta": attachments,
                        "category": category,
                        "confidence": result.get("confidence"),
                        "reasons": reasons,
                        "rawAgentResult": (result.get("raw_agent_result") or None),
                        "classifiedAt": now,
                        "ingestLog": ingest_after_class,
                    },
                },
            )
        except Exception as e:
            logger.warning("Gmail scan: upsert %s: %s", mid, e)
            continue

        try:
            await _maybe_run_document_pipeline(
                user_id=user_id,
                gmail_message_id=mid,
                msg=msg,
                service=service,
                category=category.lower().strip(),
                gs=gs,
            )
        except Exception as e:
            logger.exception("Gmail pipeline branch failed for %s: %s", mid, e)

    try:
        await prisma.gmailconnection.update(
            where={"userId": user_id},
            data={"lastSyncAt": now},
        )
    except Exception:
        pass


async def schedule_scan_background(user_id: str, swarms_ok: bool) -> None:
    await run_gmail_scan(user_id, swarms_ok=swarms_ok)


async def get_scan_row(user_id: str, scan_id: str) -> Optional[Any]:
    return await prisma.gmailscanresult.find_first(
        where={"id": scan_id, "userId": user_id},
    )
