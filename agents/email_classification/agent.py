"""Swarms agent: classify email as invoice, receipt, quote, etc."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List

from agents.agent_output_validate import normalize_email_classification_dict
from agents.llm_json_utils import json_loads_object_candidates
from agents.swarms_model_name import get_email_classification_model_name

logger = logging.getLogger("invize-backend")

VALID_CATEGORIES = frozenset(
    {"invoice", "receipt", "quote", "contract", "other", "unclear"}
)


def _cap_text(s: str, max_chars: int) -> str:
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _shrink_attachments(
    attachments: List[Dict[str, str]],
    *,
    max_items: int,
    name_max: int,
) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for a in (attachments or [])[:max_items]:
        out.append(
            {
                "filename": _cap_text(a.get("filename") or "", name_max),
                "mimeType": _cap_text(a.get("mimeType") or "", 80),
            }
        )
    return out


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

    model_name = get_email_classification_model_name()
    # Groq free tier TPM treats (prompt + max_tokens) as the request budget; Swarms defaults
    # max_tokens=4096, which alone can exceed 6000 with a modest prompt — cap completion hard.
    max_completion = max(
        64, min(1024, int(os.getenv("EMAIL_CLASSIFY_MAX_COMPLETION_TOKENS", "256")))
    )
    max_body = max(500, min(32000, int(os.getenv("EMAIL_CLASSIFY_MAX_BODY_CHARS", "2800"))))
    max_snip = max(100, min(8000, int(os.getenv("EMAIL_CLASSIFY_MAX_SNIPPET_CHARS", "400"))))
    max_subj = max(50, min(500, int(os.getenv("EMAIL_CLASSIFY_MAX_SUBJECT_CHARS", "200"))))
    max_from = max(80, min(500, int(os.getenv("EMAIL_CLASSIFY_MAX_FROM_CHARS", "160"))))
    max_att = max(1, min(40, int(os.getenv("EMAIL_CLASSIFY_MAX_ATTACHMENTS", "12"))))
    att_name_max = max(40, min(200, int(os.getenv("EMAIL_CLASSIFY_ATTACHMENT_NAME_MAX", "100"))))
    classify_retries = max(0, min(5, int(os.getenv("EMAIL_CLASSIFY_RETRY_ATTEMPTS", "2"))))

    cats = ",".join(sorted(VALID_CATEGORIES))
    system_prompt = (
        f"AP email triage. JSON in: subject,from,date,snippet,body_text,attachments[]. "
        f"category ∈ {{{cats}}} lowercase. "
        "invoice=bill/due; receipt=paid; quote=estimate; contract=legal; other=non-financial; unclear=ambiguous. "
        "Use attachment names (e.g. Invoice.pdf). Reply JSON only: "
        '{"category":"…","confidence":0.0,"reasons":["…"]}'
    )

    agent = Agent(
        agent_name="Email-Classification-Agent",
        agent_description="Classifies inbox email for invoice automation",
        system_prompt=system_prompt,
        model_name=model_name,
        max_loops=1,
        max_tokens=max_completion,
        retry_attempts=classify_retries,
        output_type="str",
        dynamic_temperature_enabled=False,
    )

    payload = {
        "subject": _cap_text(subject, max_subj),
        "from": _cap_text(from_addr, max_from),
        "date": _cap_text(date, 80),
        "snippet": _cap_text(snippet, max_snip),
        "body_text": _cap_text(body_text, max_body),
        "attachments": _shrink_attachments(
            attachments, max_items=max_att, name_max=att_name_max
        ),
    }
    start = time.time()
    try:
        compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        raw = agent.run(task=f"Classify:{compact}")
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
