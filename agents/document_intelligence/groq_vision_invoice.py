"""
Groq vision (multimodal) invoice extraction: PDFs are rasterized to JPEG
before calling the API — Groq Llama vision does not accept raw PDF bytes.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from .config import TEMP_DIR

logger = logging.getLogger(__name__)

_LINE_KEYS = ("description", "quantity", "unit_price", "amount", "tax_rate", "tax_amount", "item_code")


def _groq_api_model_id(raw: str) -> str:
    """Strip LiteLLM-style ``groq/`` prefix; Groq REST expects e.g. ``meta-llama/...``."""
    s = (raw or "").strip()
    if s.lower().startswith("groq/"):
        return s[5:].lstrip("/")
    return s


def _vision_model() -> str:
    return _groq_api_model_id(
        os.getenv(
            "GROQ_INVOICE_VISION_MODEL",
            "meta-llama/llama-4-scout-17b-16e-instruct",
        )
    )


def _max_pages() -> int:
    return max(1, min(8, int(os.getenv("GROQ_INVOICE_VISION_MAX_PAGES", "2"))))


def _pdf_dpi() -> int:
    return max(72, min(220, int(os.getenv("GROQ_INVOICE_VISION_PDF_DPI", "144"))))


def _jpeg_long_edge() -> int:
    return max(640, min(2048, int(os.getenv("GROQ_INVOICE_VISION_JPEG_MAX_EDGE", "1280"))))


def _jpeg_quality() -> int:
    return max(55, min(95, int(os.getenv("GROQ_INVOICE_VISION_JPEG_QUALITY", "82"))))


def _vision_max_tokens() -> int:
    """GST tables + line items need a generous completion budget."""
    return max(1024, min(8192, int(os.getenv("GROQ_INVOICE_VISION_MAX_TOKENS", "4096"))))


def _rasterize_to_jpeg_paths(file_path: Path, job_id: str) -> List[Path]:
    """Return paths to temporary JPEGs (caller may delete parent job dir later)."""
    out_dir = TEMP_DIR / job_id / "groq_vision"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = file_path.suffix.lower()
    paths: List[Path] = []

    if ext == ".pdf":
        import pdf2image

        pages = pdf2image.convert_from_path(
            str(file_path),
            dpi=_pdf_dpi(),
            first_page=1,
            last_page=_max_pages(),
        )
        for i, page in enumerate(pages):
            p = out_dir / f"vision_page_{i + 1}.jpg"
            w, h = page.size
            cap = _jpeg_long_edge()
            if max(w, h) > cap:
                scale = cap / float(max(w, h))
                page = page.resize(
                    (max(1, int(w * scale)), max(1, int(h * scale))),
                    Image.Resampling.LANCZOS,
                )
            page.convert("RGB").save(p, format="JPEG", quality=_jpeg_quality(), optimize=True)
            paths.append(p)
        return paths

    if ext in (".png", ".jpg", ".jpeg", ".tif", ".tiff"):
        p = out_dir / "vision_doc.jpg"
        _image_to_jpeg_base64_to_path(file_path, p)
        paths.append(p)
        return paths

    return []


def _image_to_jpeg_base64_to_path(src: Path, dest_jpg: Path) -> None:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    cap = _jpeg_long_edge()
    if max(w, h) > cap:
        scale = cap / float(max(w, h))
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
    im.save(dest_jpg, format="JPEG", quality=_jpeg_quality(), optimize=True)


def _vision_enabled() -> bool:
    if os.getenv("GROQ_INVOICE_VISION_ENABLED", "true").strip().lower() in ("0", "false", "no", "off"):
        return False
    return bool(os.getenv("GROQ_API_KEY"))


def _parse_line_items(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for row in raw[:80]:
        if not isinstance(row, dict):
            continue
        item: Dict[str, Any] = {}
        for k in _LINE_KEYS:
            if k not in row:
                continue
            v = row[k]
            if k == "description":
                item[k] = str(v).strip() if v is not None else None
            elif k == "item_code":
                item[k] = str(v).strip() if v is not None and str(v).strip() != "" else None
            else:
                if v is None or v == "":
                    item[k] = None
                else:
                    try:
                        item[k] = float(re.sub(r"[^\d.\-]", "", str(v).replace(",", "")))
                    except (TypeError, ValueError):
                        item[k] = None
        item.setdefault("confidence", 0.75)
        if item.get("description") or item.get("amount") is not None:
            out.append(item)
    return out


def _merge_float(d: Dict[str, Any], key: str, v: Any) -> None:
    if v is None or v == "":
        return
    try:
        if isinstance(v, str):
            d[key] = float(re.sub(r"[^\d.\-]", "", v.replace(",", "")))
        else:
            d[key] = float(v)
    except (TypeError, ValueError):
        pass


def _merge_str(d: Dict[str, Any], key: str, v: Any) -> None:
    if v is None:
        return
    s = str(v).strip()
    if s:
        d[key] = s


def merge_vision_invoice_payload(
    base: Dict[str, Any],
    vision: Dict[str, Any],
    *,
    overwrite: bool,
) -> Dict[str, Any]:
    """Merge vision JSON into extracted_data-shaped dict."""
    out = dict(base)
    scalar_floats = (
        "subtotal",
        "tax",
        "total",
        "discount",
        "shipping",
        "handling",
        "other_charges",
        "exchange_rate",
        "tax_rate",
    )
    scalar_strs = (
        "supplier",
        "supplier_address",
        "supplier_tax_id",
        "buyer",
        "bill_to",
        "ship_to",
        "invoice_number",
        "date",
        "due_date",
        "currency",
        "currency_symbol",
        "po_number",
        "payment_terms",
        "gstin",
        "notes",
    )

    for k in scalar_floats:
        if k not in vision:
            continue
        v = vision[k]
        cur = out.get(k)
        empty = cur is None or cur == "" or cur == 0
        if overwrite or empty:
            _merge_float(out, k, v)

    for k in scalar_strs:
        if k not in vision:
            continue
        v = vision[k]
        cur = out.get(k)
        empty = cur is None or cur == "" or cur == 0
        if overwrite or empty:
            _merge_str(out, k, v)

    if "line_items" in vision and isinstance(vision["line_items"], list):
        li = _parse_line_items(vision["line_items"])
        if li and (overwrite or not out.get("line_items")):
            out["line_items"] = li

    if any(not str(k).startswith("_") for k in vision):
        out["_groq_vision_enriched"] = True
    return out


def _call_groq_vision_sync(image_b64_list: List[str], job_id: str) -> Optional[Dict[str, Any]]:
    from groq import Groq

    from agents.llm_json_utils import json_loads_object_candidates, strip_json_fence

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or not image_b64_list:
        return None

    model = _vision_model()
    keys_doc = (
        "supplier, supplier_address, supplier_tax_id, buyer, bill_to, ship_to, "
        "invoice_number, date, due_date, currency, currency_symbol, "
        "subtotal, tax, total, tax_rate, po_number, payment_terms, gstin, notes, "
        "line_items (array of {description, quantity, unit_price, amount, item_code}). "
        "Use null if not visible. All monetary values as JSON numbers (no currency symbols)."
    )
    system = (
        "You are an expert at reading tax invoices and bills of supply from images (including Indian GST formats). "
        f"Return exactly one JSON object. Allowed keys only: {keys_doc}\n\n"
        "Party fields:\n"
        "- supplier: Legal business name of the SELLER / ISSUER (letterhead, 'Sold by', remit-to, signature block). "
        "Never use the school, college, or customer's name here.\n"
        "- buyer: Legal name of the purchaser / customer (often 'Bill to', 'Buyer', 'Consignee' when that is the customer).\n"
        "- bill_to / ship_to: addresses if shown separately from buyer name.\n"
        "- supplier_tax_id: Seller's GSTIN/UIN only (usually near supplier address). "
        "- gstin: Prefer the BUYER's GSTIN if the document labels 'Buyer GSTIN' / 'GSTIN/UIN of Buyer'; otherwise null.\n\n"
        "Money fields (critical):\n"
        "- total: The FINAL amount payable / 'Total Amount' / 'Grand Total' AFTER tax, round-off, and discounts. "
        "This is usually the largest bold figure at the bottom and may appear with ₹ or 'Rs.'. "
        "If the document shows BOTH a pre-tax subtotal AND a higher tax-inclusive total, total MUST be the tax-inclusive one.\n"
        "- subtotal: Taxable value / 'Total' column sum BEFORE CGST+SGST+IGST / amount before tax — NOT the same as total when GST lines exist. "
        "If only one clear total line exists, put it in total and set subtotal null.\n"
        "- tax: Sum of all tax amounts shown (e.g. Output CGST + Output SGST, or IGST). If separate lines, add them into one number.\n"
        "- tax_rate: Combined or headline rate if stated (e.g. 18 for 18%% GST); null if unclear.\n\n"
        "Line items:\n"
        "- Read the printed TABLE: description from the goods column; quantity from Qty/PCS column; "
        "unit_price from Rate/Price per unit (NOT the HSN code); amount from the line Amount column (row total).\n"
        "- item_code: HSN/SAC if present.\n"
        "- Include every material line; skip blank spacer rows.\n\n"
        "Other:\n"
        "- invoice_number: the invoice/challan number (e.g. 1004/25-26), not the GSTIN.\n"
        "- date: invoice date as printed (prefer ISO YYYY-MM-DD if you can infer; else exact text).\n"
        "- currency: ISO code (INR for rupee invoices).\n"
        "- Cross-check: if 'Amount in words' or similar exists, it must match your total.\n"
        "Do not invent figures; use null when illegible."
    )
    user_text = (
        f"Read all {len(image_b64_list)} page image(s) in order. Extract the JSON. "
        "Double-check total vs subtotal+tax on Indian GST invoices before responding."
    )

    content: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
    for b64 in image_b64_list:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            }
        )

    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        temperature=0.05,
        max_tokens=_vision_max_tokens(),
        response_format={"type": "json_object"},
    )
    raw = (completion.choices[0].message.content or "").strip()
    objs = json_loads_object_candidates(raw)
    if not objs:
        for candidate in (strip_json_fence(raw), raw):
            try:
                objs = [json.loads(candidate)]
                break
            except json.JSONDecodeError:
                continue
    if not objs:
        logger.warning("Groq vision: no JSON for job %s", job_id)
        return None
    payload = objs[-1]
    return payload if isinstance(payload, dict) else None


async def extract_invoice_with_groq_vision(file_path: Path, job_id: str) -> Optional[Dict[str, Any]]:
    """
    Rasterize PDF (or normalize images) to JPEG, then call Groq multimodal chat.
    Returns a flat dict of invoice fields suitable for merge_vision_invoice_payload.
    """
    if not _vision_enabled():
        return None

    try:
        jpeg_paths = await asyncio.to_thread(_rasterize_to_jpeg_paths, file_path, job_id)
        if not jpeg_paths:
            logger.info("Groq vision: no rasterized pages for job %s ext=%s", job_id, file_path.suffix)
            return None
        b64_list = await asyncio.to_thread(
            lambda: [base64.b64encode(p.read_bytes()).decode("ascii") for p in jpeg_paths],
        )
        return await asyncio.to_thread(_call_groq_vision_sync, b64_list, job_id)
    except Exception as e:
        logger.warning("Groq vision extraction failed for job %s: %s", job_id, e)
        return None
