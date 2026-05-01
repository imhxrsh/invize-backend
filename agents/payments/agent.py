"""
Groq-backed payment agent: batching / priority suggestions (human-gated in UI).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from agents.agent_output_validate import sanitize_payment_agent_output
from agents.llm_json_utils import strip_json_fence

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
        "You are a payments operations assistant. Input rows include job_id, vendor (supplier name), "
        "totals, approval_status, and optional risk_hint. "
        "Propose payment batches: group primarily by vendor when names match; otherwise by currency, due urgency, or risk. "
        "Each job_id must appear at most once—either in exactly one suggested_batches[].job_ids list or once in holds (not both). "
        "Put high-risk or missing-approval items in holds with a short reason. "
        "suggested_batches.name should be human-readable (e.g. vendor name + week). "
        "Output JSON only, no markdown: { "
        '"suggested_batches": [ { "name": string, "job_ids": string[], "rationale": string } ], '
        '"holds": [ { "job_id": string, "reason": string } ], '
        '"notes": string[] '
        "}. Advisory only—never state that money was transferred."
    )
    user = json.dumps({"invoices": items}, default=str)
    valid_job_ids = {
        str(x.get("job_id") or "").strip()
        for x in items
        if x.get("job_id") is not None and str(x.get("job_id")).strip()
    }

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
        out = None
        for candidate in (strip_json_fence(raw), raw):
            try:
                out = json.loads(candidate)
                break
            except json.JSONDecodeError:
                continue
        if not isinstance(out, dict):
            out = {}
        out["ok"] = True
        return sanitize_payment_agent_output(out, valid_job_ids)
    except Exception as e:
        logger.warning("Payment agent failed: %s", e)
        return {"ok": False, "error": str(e), "suggested_batches": [], "notes": []}
