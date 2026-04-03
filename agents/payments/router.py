"""
Payment batches (engine v1) + stub treasury + optional Groq payment agent.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from agents.document_intelligence.config import UPLOADS_DIR
from db.prisma import prisma

from .agent import run_payment_agent_suggestions
from .treasury_stub import TreasuryStub

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["Payments"])
_treasury = TreasuryStub()


class CreateBatchBody(BaseModel):
    name: Optional[str] = None


class AddLineBody(BaseModel):
    job_id: str
    amount: Optional[float] = None
    currency: str = "INR"


class AgentSuggestBody(BaseModel):
    items: List[Dict[str, Any]] = Field(default_factory=list)


def _read_job_total(job_id: str) -> tuple[Optional[float], str]:
    path = UPLOADS_DIR / f"{job_id}_result.json"
    if not path.is_file():
        return None, "INR"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        ed = data.get("extracted_data") or {}
        if not isinstance(ed, dict):
            return None, "INR"
        total = ed.get("total")
        if total is not None:
            try:
                total = float(total)
            except (TypeError, ValueError):
                total = None
        cur = ed.get("currency") or "INR"
        return total, str(cur) if cur else "INR"
    except Exception as e:
        logger.warning("read job total %s: %s", job_id, e)
        return None, "INR"


@router.get("/batches")
async def list_batches(_user=Depends(get_current_user)):
    rows = await prisma.paymentbatch.find_many(
        include={"lines": True},
        order=[{"createdAt": "desc"}],
    )
    out = []
    for b in rows:
        lines = getattr(b, "lines", None) or []
        out.append(
            {
                "id": b.id,
                "name": b.name,
                "status": b.status,
                "created_at": b.createdAt.isoformat() if b.createdAt else None,
                "lines": [
                    {
                        "id": ln.id,
                        "job_id": ln.jobId,
                        "amount": ln.amount,
                        "currency": ln.currency,
                    }
                    for ln in lines
                ],
            }
        )
    return {"batches": out}


@router.post("/batches")
async def create_batch(body: CreateBatchBody, _user=Depends(get_current_user)):
    b = await prisma.paymentbatch.create(data={"name": body.name, "status": "draft"})
    return {"id": b.id, "name": b.name, "status": b.status}


@router.post("/batches/{batch_id}/lines")
async def add_line(batch_id: str, body: AddLineBody, _user=Depends(get_current_user)):
    batch = await prisma.paymentbatch.find_unique(where={"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    if batch.status not in ("draft",):
        raise HTTPException(status_code=409, detail="Batch is not editable")

    amount = body.amount
    currency = body.currency or "INR"
    if amount is None:
        amount, currency = _read_job_total(body.job_id)
    if amount is None:
        raise HTTPException(status_code=400, detail="Could not resolve amount for job; pass amount explicitly")

    try:
        line = await prisma.paymentline.create(
            data={
                "batchId": batch_id,
                "jobId": body.job_id,
                "amount": float(amount),
                "currency": currency,
            }
        )
    except Exception as e:
        if "Unique constraint" in str(e) or "duplicate" in str(e).lower():
            raise HTTPException(status_code=409, detail="Job already in this batch") from e
        raise HTTPException(status_code=500, detail="Failed to add line") from e

    return {"id": line.id, "job_id": line.jobId, "amount": line.amount, "currency": line.currency}


@router.post("/batches/{batch_id}/submit")
async def submit_batch(batch_id: str, _user=Depends(get_current_user)):
    batch = await prisma.paymentbatch.find_unique(where={"id": batch_id}, include={"lines": True})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    lines = getattr(batch, "lines", None) or []
    if not lines:
        raise HTTPException(status_code=400, detail="Batch has no lines")

    result = _treasury.submit_batch(batch_id)
    await prisma.paymentbatch.update(where={"id": batch_id}, data={"status": "submitted"})
    return {"batch_id": batch_id, "status": "submitted", "treasury": result}


@router.post("/agent/suggest")
def agent_suggest(body: AgentSuggestBody, _user=Depends(get_current_user)):
    return run_payment_agent_suggestions(body.items)


@router.post("/batches/{batch_id}/mark-settled")
async def mark_settled(batch_id: str, _user=Depends(get_current_user)):
    """Testing / admin: move batch to settled without a real bank callback."""
    batch = await prisma.paymentbatch.find_unique(where={"id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    await prisma.paymentbatch.update(where={"id": batch_id}, data={"status": "settled"})
    return {"batch_id": batch_id, "status": "settled"}
