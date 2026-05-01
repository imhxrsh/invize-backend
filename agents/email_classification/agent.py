"""Swarms agent: classify email as invoice, receipt, quote, etc."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List

from agents.agent_output_validate import normalize_email_classification_dict
from agents.llm_json_utils import json_loads_object_candidates

logger = logging.getLogger("invize-backend")

VALID_CATEGORIES = frozenset(
    {"invoice", "receipt", "quote", "contract", "other", "unclear"}
)


def classify_email_payload(
    *,
    subject: str,
    from_addr: str,
    date: str,
    snippet: str,
    body_text: str,
    attachments: List[Dict[str, str]],
    swarms_ok: bool = True,
) -> Dict[str, Any]:
    """Return {category, confidence, reasons, raw_agent_result?, model?, error?}."""
    base = {
        "category": "unclear",
        "confidence": 0.0,
        "reasons": [],
    }
    if not swarms_ok:
        base["error"] = "swarms_unavailable"
        return base

    try:
        from swarms import Agent
    except Exception as e:
        logger.warning("Swarms unavailable for email classification: %s", e)
        base["error"] = "swarms_import_failed"
        return base

    context_name = os.getenv("ANALYSIS_CONTEXT", "Context7")
    model_name = os.getenv("AGENT_MODEL_NAME", "llama-3.3-70b-versatile")
    system_prompt = (
        f"You are an email triage agent ({context_name}). "
        "Use subject, From, Date, snippet, body text, and attachment filenames (names matter: e.g. Invoice_2024.pdf). "
        f"category must be exactly one lowercase token from: {', '.join(sorted(VALID_CATEGORIES))}. "
        "Definitions: "
        "invoice = tax invoice, bill, statement with amount due, payment request, remittance advice that is still a bill. "
        "receipt = paid confirmation, payment succeeded, thank you for your payment. "
        "quote = estimate, proposal, quotation, RFQ response. "
        "contract = agreement, MSA, SOW, legal terms. "
        "other = newsletters, marketing, internal chatter, OTPs, meeting invites, anything non-financial-document. "
        "unclear = genuinely ambiguous (do not use unclear if attachment name strongly suggests invoice). "
        "Rules: prefer invoice when PDF/image names contain invoice|bill|tax|remit|statement and body/snippet references amounts or due dates. "
        "Prefer other for no-attachment marketing or noreply newsletters even if subject says 'Invoice' as clickbait—use reasons to explain. "
        "confidence: 0.0–1.0 calibrated (high only when evidence is explicit). "
        "reasons: 1–6 short strings; include sender domain or company when it supports the label. "
        "Output ONLY valid JSON, no markdown fences, no keys besides category, confidence, reasons: "
        '{"category":"…","confidence":0.0,"reasons":["…"]}'
    )

    agent = Agent(
        agent_name="Email-Classification-Agent",
        agent_description="Classifies inbox email for invoice automation",
        system_prompt=system_prompt,
        model_name=model_name,
        max_loops=1,
        output_type="str",
        dynamic_temperature_enabled=False,
    )

    payload = {
        "subject": subject,
        "from": from_addr,
        "date": date,
        "snippet": snippet,
        "body_text": body_text,
        "attachments": attachments,
    }
    start = time.time()
    try:
        raw = agent.run(task=f"Classify this email: {json.dumps(payload)}")
        raw_str = str(raw).strip()
        duration = time.time() - start
        objs = json_loads_object_candidates(raw_str)
        if not objs:
            return {
                **base,
                "raw_agent_result": raw_str[:8000],
                "model": model_name,
                "error": "json_parse_failed",
                "execution_time": duration,
            }
        # Last JSON object in the reply usually contains the final classification.
        parsed = normalize_email_classification_dict(objs[-1])
        return {
            "category": parsed["category"],
            "confidence": parsed["confidence"],
            "reasons": parsed["reasons"],
            "raw_agent_result": raw_str[:8000],
            "model": model_name,
            "execution_time": duration,
            "parse_ok": True,
        }
    except Exception as e:
        logger.warning("Email classification agent failed: %s", e)
        return {**base, "error": str(e)[:500]}
