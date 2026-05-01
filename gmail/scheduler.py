"""Periodic Gmail inbox scan for all users with a connected account."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from config.gmail_settings import GmailSettings
from db.prisma import prisma
from gmail.service import run_gmail_scan

logger = logging.getLogger("invize-backend")


async def gmail_periodic_scan_worker(app: Any) -> None:
    """
    Sleep `GMAIL_AUTO_SCAN_STARTUP_DELAY_SECONDS`, then run `run_gmail_scan` for every
    Gmail connection, repeating every `GMAIL_AUTO_SCAN_INTERVAL_SECONDS`.
    """
    gs = GmailSettings()
    interval = gs.GMAIL_AUTO_SCAN_INTERVAL_SECONDS
    if interval <= 0:
        return

    startup_delay = max(0, min(86_400, gs.GMAIL_AUTO_SCAN_STARTUP_DELAY_SECONDS))
    if startup_delay:
        logger.info("Gmail auto-scan: first run in %ss", startup_delay)
    await asyncio.sleep(startup_delay)

    while True:
        swarms_ok = bool(getattr(app.state, "swarms_ok", False))
        try:
            conns = await prisma.gmailconnection.find_many()
            if not conns:
                logger.debug("Gmail auto-scan: no connected accounts")
            for c in conns:
                uid = str(c.userId)
                try:
                    await run_gmail_scan(uid, swarms_ok=swarms_ok)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Gmail auto-scan failed for user %s", uid)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Gmail auto-scan batch failed")

        sleep_s = max(60, min(7 * 24 * 3600, interval))
        await asyncio.sleep(sleep_s)
