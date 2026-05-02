"""Swarms agent: classify email as invoice, receipt, quote, etc."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from agents.agent_output_validate import normalize_email_classification_dict
from agents.llm_json_utils import json_loads_object_candidates
from agents.swarms_model_name import get_email_classification_model_name

logger = logging.getLogger("invize-backend")

VALID_CATEGORIES = frozenset(
    {"invoice", "receipt", "quote", "contract", "other", "unclear"}
)

# If the subject/snippet/filename mentions "invoice" but the model says ``other``/``unclear``,
# still route to the invoice document pipeline with a capped confidence score.
_INVOICE_SUBJECT_OR_NAME = re.compile(r"\b(invoice|e-?invoice|invoices)\b", re.I)

# Skip Groq when the message is very unlikely to be financial (saves TPM on bulk scans).
_FINANCE_HINT = re.compile(
    r"\b(invoice|invoices|tax\s*invoice|e-?invoice|bill(ing)?|receipt|payment\s*due|"
    r"amount\s*due|purchase\s*order|\bpo\b|p\.?\s*o\.?\s*#|quote|quotation|contract|"
    r"proforma|remittance|accounts?\s*payable|vendor|supplier|gst|gstin|1099|"
    r"wire\s*transfer|\bach\b|credit\s*note|debit\s*note)\b",
    re.I,
)
_FINANCE_FILENAME = re.compile(
    r"(invoice|inv[_\-]|bill|receipt|quote|purchase|payment|tax|gst|po[_\-]|credit|debit)",
    re.I,
)
_DOC_MIME_PREFIXES = (
    "application/pdf",
    "image/",
    "application/msword",
    "application/vnd.openxmlformats-officedocument",
)


def _heuristic_classify_skip_llm(
    *,
    subject: str,
    snippet: str,
    attachments: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    """If we can confidently label as non-financial without an LLM, return a result dict; else None."""
    if os.getenv("EMAIL_CLASSIFY_DISABLE_HEURISTIC", "").strip().lower() in ("1", "true", "yes"):
        return None

    att = attachments or []
    peek = f"{subject}\n{snippet}"
    if _FINANCE_HINT.search(peek):
        return None

    for a in att:
        fn = a.get("filename") or ""
        if _FINANCE_FILENAME.search(fn):
            return None
        mt = (a.get("mimeType") or "").lower()
        if any(mt.startswith(p) for p in _DOC_MIME_PREFIXES):
            return None

    if not att:
        return {
            "category": "other",
            "confidence": 1.0,
            "reasons": ["Heuristic: no attachments and no financial keywords in subject or snippet"],
            "heuristic": True,
        }

    low_only = True
    for a in att:
        fn_l = (a.get("filename") or "").lower()
        mt = (a.get("mimeType") or "").lower()
        is_cal = (
            fn_l.endswith(".ics")
            or "calendar" in mt
            or mt in ("text/calendar", "application/ics", "application/x-ical")
        )
        if not is_cal:
            low_only = False
            break
    if low_only:
        return {
            "category": "other",
            "confidence": 1.0,
            "reasons": ["Heuristic: only calendar-style attachments and no financial keywords"],
            "heuristic": True,
        }

    return None


def apply_invoice_mention_pipeline_boost(
    result: Dict[str, Any],
    *,
    subject: str,
    snippet: str,
    attachments: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    When subject, snippet, or an attachment filename contains ``invoice`` (word match),
    ensure category is ``invoice`` if it was not already ``invoice``/``receipt``,
    so ``_maybe_run_document_pipeline`` still runs for GMAIL_PIPELINE_CATEGORIES.
    """
    blob = "\n".join(
        [
            subject or "",
            snippet or "",
            *[a.get("filename") or "" for a in (attachments or [])],
        ]
    )
    if not _INVOICE_SUBJECT_OR_NAME.search(blob):
        return result
    cat = str(result.get("category") or "").lower().strip()
    if cat in ("invoice", "receipt"):
        return result
    reasons = list(result.get("reasons") or [])
    reasons.append(
        "Text mentions invoice; category set to invoice for ingest pipeline (confidence capped)."
    )
    try:
        c = float(result.get("confidence"))
    except (TypeError, ValueError):
        c = 0.35
    c = max(0.0, min(1.0, min(c, 0.42)))
    out = {**result, "category": "invoice", "confidence": c, "reasons": reasons[:12]}
    return out


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

    def _finalize(out: Dict[str, Any]) -> Dict[str, Any]:
        return apply_invoice_mention_pipeline_boost(
            out,
            subject=subject,
            snippet=snippet,
            attachments=attachments,
        )

    base = {
        "category": "unclear",
        "confidence": 0.0,
        "reasons": [],
    }
    if not swarms_ok:
        base["error"] = "swarms_unavailable"
        return _finalize(base)

    early = _heuristic_classify_skip_llm(
        subject=subject, snippet=snippet, attachments=attachments
    )
    if early is not None:
        return _finalize({**base, **early})

    try:
        from swarms import Agent
    except Exception as e:
        logger.warning("Swarms unavailable for email classification: %s", e)
        base["error"] = "swarms_import_failed"
        return _finalize(base)

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
        "If subject or snippet contains the word invoice (e.g. merchant 'Your order invoice'), prefer category invoice "
        "even when attachment filenames are generic (order.pdf). "
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
            return _finalize(
                {
                    **base,
                    "raw_agent_result": raw_str[:8000],
                    "model": model_name,
                    "error": "json_parse_failed",
                    "execution_time": duration,
                }
            )
        # Last JSON object in the reply usually contains the final classification.
        parsed = normalize_email_classification_dict(objs[-1])
        return _finalize(
            {
                "category": parsed["category"],
                "confidence": parsed["confidence"],
                "reasons": parsed["reasons"],
                "raw_agent_result": raw_str[:8000],
                "model": model_name,
                "execution_time": duration,
                "parse_ok": True,
            }
        )
    except Exception as e:
        logger.warning("Email classification agent failed: %s", e)
        return _finalize({**base, "error": str(e)[:500]})
