"""Gmail labels marking backend ingest completion (not the user's read/unread state)."""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("invize-backend")

_LABEL_CACHE: dict[str, str] = {}


def ensure_ingest_label_id(service: Any, label_name: str) -> Optional[str]:
    """
    Return label id for `label_name`, creating the label if missing.
    Cached per process per label name.
    """
    key = label_name.strip()
    if not key:
        return None
    if key in _LABEL_CACHE:
        return _LABEL_CACHE[key]

    def _list_and_create() -> Optional[str]:
        lst = service.users().labels().list(userId="me").execute()
        for lab in lst.get("labels") or []:
            if lab.get("name") == key:
                lid = lab.get("id")
                if lid:
                    return str(lid)
        body = {
            "name": key,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created = service.users().labels().create(userId="me", body=body).execute()
        lid = created.get("id")
        return str(lid) if lid else None

    try:
        lid = _list_and_create()
        if lid:
            _LABEL_CACHE[key] = lid
        return lid
    except Exception as e:
        logger.warning("Gmail: could not create/list label %r: %s", key, e)
        return None


def add_label_to_message(service: Any, message_id: str, label_id: str) -> bool:
    try:
        service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"addLabelIds": [label_id]},
        ).execute()
        return True
    except Exception as e:
        logger.warning("Gmail: failed to add label to message %s: %s", message_id[:20], e)
        return False
