"""
Audit trail for Verification & Compliance Agent.
Uses structlog for structured logging and optionally persists to MongoDB (DocumentAuditEvent).
"""

import json
import logging
import sys
from typing import Any, Dict, Optional

import structlog

from .config import AUDIT_LOG_ENABLED, AUDIT_LOG_TO_DB, AUDIT_LOG_FILE  # noqa: F401 - used in _configure_structlog

# Lazy import to avoid circular dependency and allow app to start if prisma not generated yet
_prisma = None

def _get_prisma():
    global _prisma
    if _prisma is None:
        try:
            from db.prisma import prisma
            _prisma = prisma
        except Exception:
            pass
    return _prisma


def _configure_structlog():
    """Configure structlog for JSON output; optional file from AUDIT_LOG_FILE."""
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ]
    logger = logging.getLogger("verification_audit")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler(sys.stdout))
        try:
            from . import config
            fh = logging.FileHandler(config.AUDIT_LOG_FILE, encoding="utf-8")
            logger.addHandler(fh)
        except Exception:
            pass
    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


_configured = False


def get_audit_logger(job_id: str, stage: str = "verification"):
    """Return a structlog logger bound with job_id and stage."""
    global _configured
    if not _configured and AUDIT_LOG_ENABLED:
        _configure_structlog()
        _configured = True
    return structlog.get_logger("verification_audit").bind(job_id=job_id, stage=stage)


async def log_audit_event(
    job_id: str,
    stage: str,
    action: str,
    details: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Log an audit event to structlog and optionally persist to DocumentAuditEvent.
    Returns the created document ID if written to DB, else None.
    """
    log = get_audit_logger(job_id, stage)
    log.info(action, **({} if details is None else details))

    event_id = None
    if AUDIT_LOG_TO_DB:
        prisma = _get_prisma()
        if prisma is not None:
            try:
                details_json = json.dumps(details, default=str) if details else None
                record = await prisma.documentauditevent.create(
                    data={
                        "jobId": job_id,
                        "stage": stage,
                        "action": action,
                        "details": details_json,
                    }
                )
                event_id = record.id
            except Exception as e:
                log.warning("audit_db_write_failed", error=str(e))
    return event_id
