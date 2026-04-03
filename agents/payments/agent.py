"""
Groq-backed payment agent: batching / priority suggestions (human-gated in UI).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def run_payment_agent_suggestions(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    items: e.g. [{ "job_id", "vendor", "total", "approval_status", "risk_hint" }, ...]
    Returns JSON with suggested_batches, notes, holds (all advisory).
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "GROQ_API_KEY not set",
            "suggested_batches": [],
            "notes": [],
        }

    model = os.getenv("GROQ_PAYMENT_AGENT_MODEL", "llama-3.3-70b-versatile")

    try:
        from groq import Groq
    except ImportError:
        return {"ok": False, "error": "groq package not installed", "suggested_batches": [], "notes": []}

    system = (
        "You are a payments operations assistant. Given invoice rows with approval and risk hints, "
        "propose how to group them into payment batches (by vendor or urgency). "
        "Respond with JSON only: { "
        '"suggested_batches": [ { "name": string, "job_ids": string[], "rationale": string } ], '
        '"holds": [ { "job_id": string, "reason": string } ], '
        '"notes": string[] '
        "}. Do not claim money was moved."
    )
    user = json.dumps({"invoices": items}, default=str)

    try:
        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=1200,
            response_format={"type": "json_object"},
        )
        raw = (completion.choices[0].message.content or "{}").strip()
        out = json.loads(raw)
        if not isinstance(out, dict):
            out = {}
        out["ok"] = True
        return out
    except Exception as e:
        logger.warning("Payment agent failed: %s", e)
        return {"ok": False, "error": str(e), "suggested_batches": [], "notes": []}
