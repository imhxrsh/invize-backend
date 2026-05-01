"""
Validate and normalize LLM / Swarms outputs before persisting or returning to clients.
Never fabricate business facts: use nulls, safe summaries, and explicit flags when parsing fails.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set

from agents.llm_json_utils import json_loads_object_candidates

logger = logging.getLogger(__name__)

_MAX_SUMMARY = 4000
_MAX_LIST_ITEMS = 8
_MAX_STRING_FIELD = 500
_SAFE_ANALYSIS_SUMMARY = (
    "Structured AI narrative was not available. Use extracted fields, verification and matching "
    "results, and the original document for decisions. Do not rely on any unstructured model text."
)

_EMAIL_CATEGORIES = frozenset(
    {"invoice", "receipt", "quote", "contract", "other", "unclear"}
)


def _trim_str(v: Any, max_len: int) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    return s[:max_len] if len(s) > max_len else s


def _optional_party_field(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    s = _trim_str(raw, 400)
    return s if s else None


def _string_list(raw: Any, max_items: int = _MAX_LIST_ITEMS) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s[:_MAX_STRING_FIELD]] if s else []
    if isinstance(raw, list):
        out: List[str] = []
        for x in raw[: max_items * 2]:
            if x is None:
                continue
            s = _trim_str(x, _MAX_STRING_FIELD)
            if s:
                out.append(s)
            if len(out) >= max_items:
                break
        return out
    s = _trim_str(raw, _MAX_STRING_FIELD)
    return [s] if s else []


def _invoice_dict_has_signal(obj: Dict[str, Any]) -> bool:
    s = obj.get("summary")
    if isinstance(s, str) and len(s.strip()) >= 12:
        return True
    if obj.get("supplier_guess") is not None or obj.get("buyer_guess") is not None:
        return True
    for k in ("flags", "recommendations"):
        v = obj.get(k)
        if isinstance(v, list) and len(v) > 0:
            return True
    return False


def coerce_invoice_analysis_dict(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a parsed JSON object into the canonical invoice-analysis shape (no _meta)."""
    summary_raw = obj.get("summary")
    if isinstance(summary_raw, str) and summary_raw.strip():
        summary = summary_raw.strip()[:_MAX_SUMMARY]
    else:
        summary = "The model did not return a usable summary."

    return {
        "summary": summary,
        "supplier_guess": _optional_party_field(obj.get("supplier_guess")),
        "buyer_guess": _optional_party_field(obj.get("buyer_guess")),
        "flags": _string_list(obj.get("flags")),
        "recommendations": _string_list(obj.get("recommendations")),
    }


def normalize_invoice_analysis_swarms(raw_llm_text: str) -> Dict[str, Any]:
    """
    Parse Swarms invoice analysis text into a canonical JSON-serializable dict.
    Always returns the same key shape; _meta.parse_ok is False when output was not trustworthy JSON.
    """
    text = (raw_llm_text or "").strip()
    candidates = json_loads_object_candidates(text)

    for obj in candidates:
        if not isinstance(obj, dict):
            continue
        body = coerce_invoice_analysis_dict(obj)
        warnings: List[str] = []
        if not _invoice_dict_has_signal(obj):
            warnings.append("low_signal_output")
        return {
            **body,
            "_meta": {
                "parse_ok": True,
                "warnings": warnings,
            },
        }

    logger.info(
        "Invoice analysis: no JSON object parsed from model output (chars=%s)",
        len(text),
    )
    return {
        "summary": _SAFE_ANALYSIS_SUMMARY,
        "supplier_guess": None,
        "buyer_guess": None,
        "flags": ["ai_analysis_unparseable"],
        "recommendations": [
            "Review extracted_data and the source document.",
            "If this persists, verify AGENT_MODEL_NAME and Swarms connectivity.",
        ],
        "_meta": {
            "parse_ok": False,
            "warnings": ["Model output was not valid JSON."],
        },
    }


def merge_invoice_analysis_with_extracted(
    normalized: Dict[str, Any],
    extracted_supplier: Optional[str],
    extracted_buyer: Optional[str],
) -> Dict[str, Any]:
    """
    If model guesses disagree strongly from extracted supplier, add a flag (no overwrites).
    """
    if normalized.get("_meta", {}).get("parse_ok") is False:
        return normalized
    sg = normalized.get("supplier_guess")
    if (
        isinstance(sg, str)
        and sg.strip()
        and isinstance(extracted_supplier, str)
        and extracted_supplier.strip()
        and sg.strip().lower() != extracted_supplier.strip().lower()
        and extracted_supplier.strip().lower() not in sg.strip().lower()
        and sg.strip().lower() not in extracted_supplier.strip().lower()
    ):
        flags = list(normalized.get("flags") or [])
        hint = "ai_supplier_guess_differs_from_extracted_supplier"
        if hint not in flags:
            flags = (flags + [hint])[-_MAX_LIST_ITEMS:]
            normalized = {**normalized, "flags": flags}
    bg = normalized.get("buyer_guess")
    if (
        isinstance(bg, str)
        and bg.strip()
        and isinstance(extracted_buyer, str)
        and extracted_buyer.strip()
        and bg.strip().lower() != extracted_buyer.strip().lower()
        and extracted_buyer.strip().lower() not in bg.strip().lower()
        and bg.strip().lower() not in extracted_buyer.strip().lower()
    ):
        flags = list(normalized.get("flags") or [])
        hint = "ai_buyer_guess_differs_from_extracted_buyer"
        if hint not in flags:
            flags = (flags + [hint])[-_MAX_LIST_ITEMS:]
            normalized = {**normalized, "flags": flags}
    return normalized


def sanitize_payment_agent_output(
    out: Dict[str, Any],
    valid_job_ids: Set[str],
) -> Dict[str, Any]:
    """Keep only known job_ids; no duplicates across batches and holds."""
    batches_raw = out.get("suggested_batches")
    if not isinstance(batches_raw, list):
        batches_raw = []
    holds_raw = out.get("holds")
    if not isinstance(holds_raw, list):
        holds_raw = []
    notes_raw = out.get("notes")
    if not isinstance(notes_raw, list):
        notes_raw = []

    assigned: Set[str] = set()
    clean_batches: List[Dict[str, Any]] = []

    for b in batches_raw:
        if not isinstance(b, dict):
            continue
        name = _trim_str(b.get("name"), 200) or "Batch"
        ids_raw = b.get("job_ids")
        if not isinstance(ids_raw, list):
            ids_raw = []
        clean_ids: List[str] = []
        for jid in ids_raw:
            sj = _trim_str(jid, 128)
            if not sj or sj not in valid_job_ids or sj in assigned:
                continue
            assigned.add(sj)
            clean_ids.append(sj)
        rationale = _trim_str(b.get("rationale"), 1000)
        if clean_ids:
            clean_batches.append({"name": name, "job_ids": clean_ids, "rationale": rationale})

    clean_holds: List[Dict[str, Any]] = []
    for h in holds_raw:
        if not isinstance(h, dict):
            continue
        sj = _trim_str(h.get("job_id"), 128)
        if not sj or sj not in valid_job_ids or sj in assigned:
            continue
        assigned.add(sj)
        reason = _trim_str(h.get("reason"), 500) or "Held for review"
        clean_holds.append({"job_id": sj, "reason": reason})

    clean_notes = [_trim_str(x, 500) for x in notes_raw if _trim_str(x, 500)][:20]
    missing = valid_job_ids - assigned
    if missing:
        clean_notes.append(
            "Some invoices were not placed in a batch or hold (invalid or duplicate job_id in model output): "
            + ", ".join(sorted(missing)[:20])
            + ("…" if len(missing) > 20 else "")
        )

    out = dict(out)
    out["suggested_batches"] = clean_batches
    out["holds"] = clean_holds
    out["notes"] = clean_notes
    out["_validation"] = {
        "expected_jobs": len(valid_job_ids),
        "assigned_jobs": len(assigned),
        "complete": len(missing) == 0,
    }
    return out


def normalize_email_classification_dict(parsed: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(parsed, dict):
        return {"category": "unclear", "confidence": 0.0, "reasons": ["invalid_model_payload"]}
    cat = str(parsed.get("category", "unclear")).lower().strip()
    if cat not in _EMAIL_CATEGORIES:
        cat = "unclear"
    conf = parsed.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else 0.5
    except (TypeError, ValueError):
        conf_f = 0.5
    conf_f = max(0.0, min(1.0, conf_f))
    reasons = parsed.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    reasons = [_trim_str(r, 400) for r in reasons if _trim_str(r, 400)][:12]
    return {"category": cat, "confidence": conf_f, "reasons": reasons}


def should_retry_swarms_json() -> bool:
    return os.getenv("AGENT_JSON_RETRY", "true").lower() in ("1", "true", "yes")


def invoice_analysis_retry_task() -> str:
    return (
        "Your previous reply was not usable. Output exactly one JSON object, no markdown, with keys: "
        "summary (string), supplier_guess (string or null), buyer_guess (string or null), "
        "flags (array of strings), recommendations (array of strings). "
        "Use null when unsure. Do not invent amounts or invoice numbers not in the payload."
    )
