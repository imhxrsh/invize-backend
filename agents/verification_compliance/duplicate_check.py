"""
Duplicate detection: fuzzy match on invoice number/amount/date + optional perceptual hash.
Uses RapidFuzz and imagededup; stores fingerprints in ProcessedDocumentFingerprint.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

from .config import (
    DUPLICATE_CHECK_ENABLED,
    DUPLICATE_INVOICE_NUMBER_THRESHOLD,
    DUPLICATE_HASH_MAX_DISTANCE,
    DUPLICATE_LOOKBACK_DAYS,
)
from .models import DuplicateCheckResult

logger = logging.getLogger(__name__)

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


def _normalize_invoice_key(extracted: Dict[str, Any]) -> tuple:
    """Normalize invoice_number, total, date for comparison."""
    inv = (extracted.get("invoice_number") or "").strip()
    total = extracted.get("total")
    if total is not None:
        try:
            total = float(total)
        except (TypeError, ValueError):
            total = None
    date_val = (extracted.get("date") or "").strip()
    return (inv, total, date_val)


def _get_first_page_image_path(file_path: Path, job_id: str) -> Optional[Path]:
    """Return path to first page as image for hashing (PDF -> image if needed)."""
    if file_path.suffix.lower() == ".pdf":
        try:
            from pdf2image import convert_from_path
            from .config import AGENT_WORKSPACE
            temp_dir = AGENT_WORKSPACE / "temp" / job_id
            temp_dir.mkdir(parents=True, exist_ok=True)
            pages = convert_from_path(file_path, first_page=1, last_page=1, dpi=150)
            if pages:
                first_page_path = temp_dir / "first_page.jpg"
                pages[0].save(first_page_path, "JPEG")
                return first_page_path
        except Exception as e:
            logger.warning("Could not convert PDF first page for hash: %s", e)
        return None
    if file_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".tiff", ".tif"):
        return file_path
    return None


def _compute_content_hash(image_path: Path) -> Optional[str]:
    """Compute perceptual hash (PHash) for image at path. Requires imagededup."""
    try:
        from imagededup.methods import PHash
    except ImportError:
        return None
    try:
        phasher = PHash()
        h = phasher.encode_image(image_file=str(image_path))
        return h
    except Exception as e:
        logger.warning("Content hash failed: %s", e)
        return None


async def run_duplicate_check(
    job_id: str,
    file_path: Path,
    validated_data: Dict[str, Any],
) -> DuplicateCheckResult:
    """
    Check for duplicates: fetch recent fingerprints, fuzzy match + optional hash.
    If no duplicate, persist new fingerprint. Returns DuplicateCheckResult.
    """
    if not DUPLICATE_CHECK_ENABLED:
        return DuplicateCheckResult()

    extracted = validated_data.get("extracted_data") or {}
    inv_number = (extracted.get("invoice_number") or "").strip()
    total = extracted.get("total")
    date_str = (extracted.get("date") or "").strip()
    supplier = (extracted.get("supplier") or "").strip()

    prisma = _get_prisma()
    if prisma is None:
        logger.warning("Prisma not available; skipping duplicate check DB lookup")
        return DuplicateCheckResult()

    # Fetch recent fingerprints (lookback window)
    since = datetime.now(timezone.utc) - timedelta(days=DUPLICATE_LOOKBACK_DAYS)
    try:
        candidates = await prisma.processeddocumentfingerprint.find_many(
            where={"createdAt": {"gte": since}},
            order={"createdAt": "desc"},
            take=5000,
        )
    except Exception as e:
        logger.warning("Failed to fetch fingerprints: %s", e)
        return DuplicateCheckResult()

    if not candidates:
        # No history; persist current and return not duplicate
        await _persist_fingerprint(
            prisma, job_id, file_path, inv_number, total, date_str, supplier
        )
        return DuplicateCheckResult(is_duplicate=False)

    # Build choice list for RapidFuzz: use composite key string for matching
    choices = []
    for c in candidates:
        inv = c.invoiceNumber or ""
        dt = c.invoiceDate or ""
        choices.append((c.jobId, inv, c.total, dt))

    from rapidfuzz import fuzz, process

    # Match on invoice number (primary)
    query_inv = inv_number or ""
    if not query_inv:
        query_inv = "_"
    choice_strings = [c[1] for c in choices]
    best = process.extractOne(
        query_inv,
        choice_strings,
        scorer=fuzz.WRatio,
        score_cutoff=DUPLICATE_INVOICE_NUMBER_THRESHOLD,
    )
    matched_job_ids: List[str] = []
    scores: Dict[str, float] = {}
    content_hash_matched = False

    if best is not None:
        _match_str, score, idx = best[0], best[1], best[2]
        cand = candidates[idx]
        matched_job_ids.append(cand.jobId)
        scores[cand.jobId] = float(score)

        # Optional: confirm with content hash if we have image
        img_path = _get_first_page_image_path(file_path, job_id)
        if img_path and cand.contentHash:
            new_hash = _compute_content_hash(img_path)
            if new_hash:
                try:
                    from imagededup.methods import PHash
                    phasher = PHash()
                    dist = phasher.hamming_distance(new_hash, cand.contentHash)
                    if dist <= DUPLICATE_HASH_MAX_DISTANCE:
                        content_hash_matched = True
                except (ImportError, Exception):
                    pass

    is_duplicate = len(matched_job_ids) > 0

    # Persist fingerprint for this job (so future runs can match against it)
    await _persist_fingerprint(
        prisma, job_id, file_path, inv_number, total, date_str, supplier
    )

    return DuplicateCheckResult(
        is_duplicate=is_duplicate,
        matched_job_ids=matched_job_ids,
        scores=scores,
        content_hash_matched=content_hash_matched,
    )


async def _persist_fingerprint(
    prisma,
    job_id: str,
    file_path: Path,
    invoice_number: Optional[str],
    total: Optional[float],
    invoice_date: Optional[str],
    supplier: Optional[str],
) -> None:
    """Insert or update ProcessedDocumentFingerprint for this job."""
    content_hash = None
    img_path = _get_first_page_image_path(file_path, job_id)
    if img_path:
        content_hash = _compute_content_hash(img_path)

    try:
        await prisma.processeddocumentfingerprint.upsert(
            where={"jobId": job_id},
            data={
                "create": {
                    "jobId": job_id,
                    "invoiceNumber": invoice_number,
                    "total": float(total) if total is not None else None,
                    "invoiceDate": invoice_date,
                    "supplier": supplier,
                    "contentHash": content_hash,
                },
                "update": {
                    "invoiceNumber": invoice_number,
                    "total": float(total) if total is not None else None,
                    "invoiceDate": invoice_date,
                    "supplier": supplier,
                    "contentHash": content_hash,
                },
            },
        )
    except Exception as e:
        logger.warning("Failed to persist fingerprint for %s: %s", job_id, e)
