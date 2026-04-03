"""
Optional Groq JSON extraction to fill missing invoice fields from OCR text.
Uses official groq client with json_object response format.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Fields we may fill (subset of ExtractedData numerics / strings)
_FILL_KEYS = [
    "supplier",
    "invoice_number",
    "date",
    "due_date",
    "currency",
    "subtotal",
    "tax",
    "total",
    "po_number",
]


def _needs_enrichment(extracted: Dict[str, Any]) -> bool:
    total = extracted.get("total")
    has_total = total is not None and total != "" and total != 0
    inv = extracted.get("invoice_number")
    has_inv = inv is not None and str(inv).strip() != ""
    # Trigger if money fields missing but we might still have text
    return not has_total or not has_inv


def _truncate_text(text: str, max_chars: int = 12000) -> str:
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars // 2] + "\n...\n" + t[-max_chars // 2 :]


async def enrich_extracted_with_groq(
    extracted: Dict[str, Any],
    raw_text: Optional[str],
    job_id: str,
) -> Dict[str, Any]:
    """
    If GROQ_API_KEY is set and key fields are missing, ask Groq for JSON fields.
    Merge only non-null values into extracted (does not remove existing good values).
    """
    if not raw_text or not _needs_enrichment(extracted):
        return extracted

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return extracted

    model = os.getenv("GROQ_EXTRACTION_MODEL", "llama-3.3-70b-versatile")

    try:
        from groq import Groq
    except ImportError:
        logger.warning("groq package not installed; skip LLM extraction for job %s", job_id)
        return extracted

    snippet = _truncate_text(raw_text)
    system = (
        "You extract structured invoice data from raw OCR text. "
        "Respond with a single JSON object only. Use null for unknown fields. "
        "Numbers must be JSON numbers (no currency symbols). "
        f"Allowed keys: {json.dumps(_FILL_KEYS)}. "
        "For currency use ISO 4217 code when possible (e.g. INR, USD)."
    )
    user = f"OCR text:\n{snippet}"

    client = Groq(api_key=api_key)
    try:
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        content = (completion.choices[0].message.content or "").strip()
        payload = json.loads(content)
    except Exception as e:
        logger.warning("Groq extraction failed for job %s: %s", job_id, e)
        return extracted

    if not isinstance(payload, dict):
        return extracted

    merged = dict(extracted)
    filled: List[str] = []
    for k in _FILL_KEYS:
        if k not in payload:
            continue
        v = payload[k]
        if v is None:
            continue
        cur = merged.get(k)
        if cur is not None and cur != "" and cur != 0:
            continue
        if k in ("subtotal", "tax", "total"):
            try:
                if isinstance(v, str):
                    v = float(re.sub(r"[^\d.\-]", "", v.replace(",", "")))
                else:
                    v = float(v)
            except (TypeError, ValueError):
                continue
        else:
            v = str(v).strip()
            if not v:
                continue
        merged[k] = v
        filled.append(k)

    if filled:
        merged["_groq_enriched"] = True
        merged["_groq_fields"] = filled
        logger.info("Groq filled fields for job %s: %s", job_id, filled)

    return merged
