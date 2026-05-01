"""Pick and download Gmail attachments for the document pipeline."""

from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional, Tuple

from agents.document_intelligence.config import MAX_FILE_SIZE_MB, SUPPORTED_FORMATS

logger = logging.getLogger("invize-backend")

MIME_EXT = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/tiff": "tiff",
    "image/tif": "tif",
    "text/plain": "txt",
}


def _ext_from_filename(name: str) -> str:
    if "." not in name:
        return ""
    return name.rsplit(".", 1)[-1].lower().strip()


def _ext_from_mime(mime: str) -> str:
    m = (mime or "").lower().split(";")[0].strip()
    return MIME_EXT.get(m, "")


def _walk_collect(part: Dict[str, Any], out: List[Dict[str, Any]]) -> None:
    body = part.get("body") or {}
    fn = (part.get("filename") or "").strip()
    mime = (part.get("mimeType") or "").lower()
    aid = body.get("attachmentId")
    data = body.get("data")
    size = int(body.get("size") or 0)

    if aid:
        out.append(
            {
                "attachment_id": aid,
                "filename": fn or "attachment",
                "mime": mime,
                "size": size,
                "inline_b64": None,
            }
        )
    elif fn and data:
        out.append(
            {
                "attachment_id": None,
                "filename": fn,
                "mime": mime,
                "size": size,
                "inline_b64": data,
            }
        )

    for child in part.get("parts") or []:
        _walk_collect(child, out)


def collect_fetchable_attachments(msg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Parts with attachmentId (API fetch) or inline body.data + filename."""
    payload = msg.get("payload") or {}
    out: List[Dict[str, Any]] = []
    body = payload.get("body") or {}
    fn = (payload.get("filename") or "").strip()
    mime = (payload.get("mimeType") or "").lower()
    if body.get("attachmentId"):
        _walk_collect(payload, out)
    elif fn and body.get("data"):
        out.append(
            {
                "attachment_id": None,
                "filename": fn,
                "mime": mime,
                "size": int(body.get("size") or 0),
                "inline_b64": body.get("data"),
            }
        )
    for p in payload.get("parts") or []:
        _walk_collect(p, out)
    return out


def pick_processable_attachment(
    candidates: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    for c in candidates:
        fn = c.get("filename") or ""
        mime = c.get("mime") or ""
        ext = _ext_from_filename(fn) or _ext_from_mime(mime)
        if ext in SUPPORTED_FORMATS:
            c = {**c, "_resolved_ext": ext}
            return c
    return None


def decode_inline_bytes(inline_b64: str) -> bytes:
    pad = "=" * (-len(inline_b64) % 4)
    return base64.urlsafe_b64decode((inline_b64 + pad).encode())


def fetch_attachment_bytes(
    service: Any,
    message_id: str,
    candidate: Dict[str, Any],
) -> Tuple[bytes, str]:
    """Return file bytes and extension (no dot)."""
    ext = candidate.get("_resolved_ext") or "bin"
    if candidate.get("inline_b64"):
        return decode_inline_bytes(candidate["inline_b64"]), ext

    aid = candidate.get("attachment_id")
    if not aid:
        raise ValueError("No attachment id or inline data")

    def _get():
        return (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=aid)
            .execute()
        )

    meta = _get()
    data = meta.get("data") or ""
    if not data:
        raise ValueError("Empty attachment body")
    pad = "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode((data + pad).encode())
    return raw, ext


def max_attachment_bytes(gs_max_mb: int) -> int:
    cap_mb = min(MAX_FILE_SIZE_MB, max(1, gs_max_mb))
    return cap_mb * 1024 * 1024
