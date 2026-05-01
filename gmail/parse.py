"""Extract plain text and attachment metadata from Gmail API message payloads."""

from __future__ import annotations

import base64
from typing import Any, Dict, List, Tuple

MAX_BODY_CHARS = 16_000


def _header_map(payload: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for h in payload.get("headers") or []:
        name = (h.get("name") or "").lower()
        if name:
            out[name] = h.get("value") or ""
    return out


def _decode_body_data(data: str | None) -> str:
    if not data:
        return ""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _walk_parts(
    part: Dict[str, Any],
    text_chunks: List[str],
    attachments: List[Dict[str, str]],
) -> None:
    filename = (part.get("filename") or "").strip()
    mime = part.get("mimeType") or ""
    body = part.get("body") or {}

    if filename:
        attachments.append({"filename": filename, "mimeType": mime})

    if mime == "text/plain" and body.get("data"):
        text_chunks.append(_decode_body_data(body.get("data")))

    for child in part.get("parts") or []:
        _walk_parts(child, text_chunks, attachments)


def extract_from_message(msg: Dict[str, Any]) -> Tuple[str, str, str, str, str, List[Dict[str, str]]]:
    """Returns subject, from_addr, date, snippet, body_preview, attachments."""
    payload = msg.get("payload") or {}
    headers = _header_map(payload)
    subject = headers.get("subject", "")
    from_addr = headers.get("from", "")
    date = headers.get("date", "")
    snippet = msg.get("snippet") or ""

    text_chunks: List[str] = []
    attachments: List[Dict[str, str]] = []

    if payload.get("mimeType") == "text/plain" and (payload.get("body") or {}).get("data"):
        text_chunks.append(_decode_body_data((payload.get("body") or {}).get("data")))
    for p in payload.get("parts") or []:
        _walk_parts(p, text_chunks, attachments)

    body = "\n".join(text_chunks).strip()
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n…"

    return subject, from_addr, date, snippet, body, attachments
