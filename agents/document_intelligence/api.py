"""
FastAPI router for Document Intelligence Agent
"""

import uuid
import json
import logging
import os
import mimetypes
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime, timezone

from pydantic import ValidationError
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Depends
from fastapi.responses import FileResponse

from auth.dependencies import get_current_user

from .models import (
    DocumentUploadResponse,
    DocumentStatusResponse,
    DocumentResultResponse,
    DocumentStatus,
    VerificationComplianceResult,
    MatchingERPResult,
    OperationsWorkflowBlock,
)
from .config import UPLOADS_DIR, MAX_FILE_SIZE_MB, SUPPORTED_FORMATS
from .processor import DocumentProcessor

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Document Intelligence"])
processor = DocumentProcessor()


def _progress_from_status(status_data: dict) -> Tuple[Optional[str], Optional[List[str]]]:
    """Current progress line and ordered history for UIs that poll `/result` or `/status`."""
    prog = status_data.get("progress")
    if prog is not None:
        prog = str(prog) if prog else None
    raw_hist = status_data.get("progress_history")
    hist = None
    if isinstance(raw_hist, list):
        hist = [str(x) for x in raw_hist if x is not None]
    return prog, hist


def _parse_stored_document_result(job_id: str, result_data: dict) -> DocumentResultResponse:
    """Build DocumentResultResponse from on-disk JSON without 500s on minor drift."""
    payload = dict(result_data)
    payload["job_id"] = payload.get("job_id") or job_id
    try:
        return DocumentResultResponse.model_validate(payload)
    except ValidationError as e:
        logger.warning("Document result validate (pass 1) job=%s: %s", job_id, e)
        vc = payload.get("verification_compliance")
        if isinstance(vc, dict):
            ids = vc.get("audit_event_ids")
            if ids is not None and not isinstance(ids, list):
                vc = {**vc, "audit_event_ids": []}
            elif isinstance(ids, list):
                vc = {**vc, "audit_event_ids": [str(x) for x in ids]}
            payload["verification_compliance"] = vc
        try:
            return DocumentResultResponse.model_validate(payload)
        except ValidationError as e2:
            logger.warning("Document result validate (pass 2) job=%s: %s", job_id, e2)
            st_raw = str(payload.get("status", "completed")).lower()
            try:
                st = DocumentStatus(st_raw)
            except ValueError:
                st = DocumentStatus.COMPLETED
            aa = payload.get("agent_analysis")
            return DocumentResultResponse(
                job_id=job_id,
                status=st,
                error="Stored result partially invalid; some fields were omitted.",
                extracted_data=None,
                agent_analysis=aa if isinstance(aa, dict) else None,
            )


def _list_documents_from_fs():
    """Scan UPLOADS_DIR for *_status.json and return list of job summaries."""
    import os
    out = []
    if not UPLOADS_DIR.exists():
        return out
    for f in sorted(UPLOADS_DIR.glob("*_status.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            job_id = f.name.replace("_status.json", "")
            with open(f, "r") as fp:
                data = json.load(fp)
            status = data.get("status", "pending")
            filename = data.get("filename")
            created_at = None
            try:
                mtime = os.path.getmtime(f)
                created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            except OSError:
                pass
            # Optional: enrich with result (vendor, total) if available
            result_file = UPLOADS_DIR / f"{job_id}_result.json"
            vendor = None
            total = None
            invoice_number = None
            currency = None
            approval_status = None
            has_exception = False
            if result_file.exists():
                try:
                    with open(result_file, "r") as rp:
                        res = json.load(rp)
                    ed = res.get("extracted_data") or {}
                    if isinstance(ed, dict):
                        vendor = ed.get("supplier")
                        total = ed.get("total")
                        invoice_number = ed.get("invoice_number")
                        currency = ed.get("currency") or ed.get("currency_symbol")
                    else:
                        vendor = getattr(ed, "supplier", None)
                        total = getattr(ed, "total", None)
                    ow = res.get("operations_workflow") or {}
                    if isinstance(ow, dict):
                        summ = ow.get("approval_summary") or {}
                        if isinstance(summ, dict):
                            approval_status = summ.get("status")
                        has_exception = bool(ow.get("exception"))
                except Exception:
                    pass
            out.append({
                "job_id": job_id,
                "status": status,
                "filename": filename,
                "created_at": created_at,
                "vendor": vendor,
                "total": total,
                "invoice_number": invoice_number,
                "currency": currency,
                "approval_status": approval_status,
                "has_exception": has_exception,
            })
        except Exception as e:
            logger.warning("Skip status file %s: %s", f, e)
    return out


def _aggregate_vendors():
    """Aggregate unique vendors (suppliers) from result files with total and count."""
    agg = {}
    if not UPLOADS_DIR.exists():
        return list(agg.values())
    for f in UPLOADS_DIR.glob("*_result.json"):
        try:
            with open(f, "r") as fp:
                res = json.load(fp)
            ed = res.get("extracted_data") or {}
            if not isinstance(ed, dict):
                continue
            vendor = (ed.get("supplier") or "").strip()
            if not vendor:
                continue
            total = ed.get("total")
            try:
                total = float(total) if total is not None else 0
            except (TypeError, ValueError):
                total = 0
            if vendor not in agg:
                agg[vendor] = {"name": vendor, "total": 0, "invoice_count": 0}
            agg[vendor]["total"] += total
            agg[vendor]["invoice_count"] += 1
        except Exception as e:
            logger.warning("Skip result file %s: %s", f, e)
    return sorted(agg.values(), key=lambda x: (-x["total"], x["name"]))


@router.get("/vendors")
async def list_vendors(_user=Depends(get_current_user)):
    """List vendors (suppliers) aggregated from processed document results."""
    try:
        vendors = _aggregate_vendors()
        return {"vendors": vendors, "total": len(vendors)}
    except Exception as e:
        logger.exception("list_vendors failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list vendors")


@router.get("", include_in_schema=False)
@router.get("/")
async def list_documents(_user=Depends(get_current_user)):
    """List documents (jobs) from uploads; each has job_id, status, filename, vendor/total when result exists."""
    try:
        items = _list_documents_from_fs()
        return {"items": items, "total": len(items)}
    except Exception as e:
        logger.exception("list_documents failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list documents")


@router.post("", response_model=DocumentUploadResponse, include_in_schema=False)
@router.post("/", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    _user=Depends(get_current_user),
):
    """Upload a document for processing"""
    
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    
    # Check file extension
    file_ext = file.filename.split('.')[-1].lower()
    if file_ext not in SUPPORTED_FORMATS:
        raise HTTPException(
            status_code=400, 
            detail=f"Unsupported format. Supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    
    # Check file size
    file_size_mb = len(await file.read()) / (1024 * 1024)
    await file.seek(0)  # Reset file pointer
    
    if file_size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400, 
            detail=f"File too large. Maximum size: {MAX_FILE_SIZE_MB}MB"
        )
    
    # Generate job ID and save file
    job_id = str(uuid.uuid4())
    file_path = UPLOADS_DIR / f"{job_id}.{file_ext}"
    
    try:
        # Save uploaded file
        with open(file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # Create status file
        status_file = UPLOADS_DIR / f"{job_id}_status.json"
        status_data = {
            "job_id": job_id,
            "status": DocumentStatus.PENDING,
            "filename": file.filename,
            "file_path": str(file_path)
        }
        
        with open(status_file, "w") as f:
            json.dump(status_data, f)
        
        # Start processing in background
        background_tasks.add_task(processor.process_document, job_id, file_path)
        
        logger.info(f"Document uploaded: {job_id}")
        
        return DocumentUploadResponse(
            job_id=job_id,
            status=DocumentStatus.PENDING,
            message="Document uploaded successfully. Processing started."
        )
        
    except Exception as e:
        logger.error(f"Error uploading document: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload document")


@router.get("/{job_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(job_id: str, _user=Depends(get_current_user)):
    """Get processing status of a document"""
    
    status_file = UPLOADS_DIR / f"{job_id}_status.json"
    
    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
        
        raw_hist = status_data.get("progress_history")
        progress_history = (
            raw_hist if isinstance(raw_hist, list) else None
        )
        if progress_history is not None:
            progress_history = [str(x) for x in progress_history if x is not None]

        return DocumentStatusResponse(
            job_id=job_id,
            status=status_data.get("status", DocumentStatus.PENDING),
            progress=status_data.get("progress"),
            progress_history=progress_history,
            error=status_data.get("error")
        )
        
    except Exception as e:
        logger.error(f"Error reading status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to read status")


@router.get("/{job_id}/result", response_model=DocumentResultResponse)
async def get_document_result(job_id: str, _user=Depends(get_current_user)):
    """Get processing result of a document"""
    
    result_file = UPLOADS_DIR / f"{job_id}_result.json"
    status_file = UPLOADS_DIR / f"{job_id}_status.json"
    
    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Read status
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception as e:
        logger.error(f"Error reading status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to read status")
    
    status = status_data.get("status", DocumentStatus.PENDING)
    prog, hist = _progress_from_status(status_data)
    
    if status == DocumentStatus.PENDING or status == DocumentStatus.PROCESSING:
        return DocumentResultResponse(
            job_id=job_id,
            status=status,
            error=None,
            progress=prog,
            progress_history=hist,
        )
    
    if status == DocumentStatus.FAILED:
        return DocumentResultResponse(
            job_id=job_id,
            status=status,
            error=status_data.get("error", "Processing failed"),
            progress=prog,
            progress_history=hist,
        )
    
    # Read result if completed
    if not result_file.exists():
        return DocumentResultResponse(
            job_id=job_id,
            status=DocumentStatus.FAILED,
            error="Result file not found",
            progress=prog,
            progress_history=hist,
        )
    
    try:
        with open(result_file, "r") as f:
            result_data = json.load(f)

        parsed = _parse_stored_document_result(job_id, result_data)
        return parsed.model_copy(
            update={
                "progress": prog,
                "progress_history": hist,
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reading result: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to read result")


@router.get("/{job_id}/verification", response_model=VerificationComplianceResult)
async def get_document_verification(job_id: str, _user=Depends(get_current_user)):
    """
    Get Verification & Compliance result for a document (duplicate check, authenticity, audit).
    Returns the same data as the `verification_compliance` field in GET /documents/{job_id}/result.
    Use this when you only need verification data without the full extraction result.
    """
    result_file = UPLOADS_DIR / f"{job_id}_result.json"
    status_file = UPLOADS_DIR / f"{job_id}_status.json"

    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception as e:
        logger.error("Error reading status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read status")

    status = status_data.get("status", "pending")
    if status != DocumentStatus.COMPLETED.value and status != DocumentStatus.COMPLETED:
        raise HTTPException(
            status_code=404,
            detail=f"Verification not available (job status: {status}). Process the document first and wait for completion.",
        )

    if not result_file.exists():
        raise HTTPException(status_code=404, detail="Result not found")

    try:
        with open(result_file, "r") as f:
            result_data = json.load(f)
    except Exception as e:
        logger.error("Error reading result: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read result")

    verification = result_data.get("verification_compliance")
    if verification is None:
        raise HTTPException(
            status_code=404,
            detail="No verification data for this job (verification may be disabled or job ran before verification was added).",
        )

    return VerificationComplianceResult(**verification)


@router.get("/{job_id}/matching", response_model=MatchingERPResult)
async def get_document_matching(job_id: str, _user=Depends(get_current_user)):
    """
    Get Matching & ERP result for a document (PO match, variances, vendor validation).
    Returns the same data as the `matching_erp` field in GET /documents/{job_id}/result.
    Demo data only; Tally and SAP connectors to be built later.
    """
    result_file = UPLOADS_DIR / f"{job_id}_result.json"
    status_file = UPLOADS_DIR / f"{job_id}_status.json"

    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception as e:
        logger.error("Error reading status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read status")

    status = status_data.get("status", "pending")
    if status != DocumentStatus.COMPLETED.value and status != DocumentStatus.COMPLETED:
        raise HTTPException(
            status_code=404,
            detail=f"Matching not available (job status: {status}). Process the document first and wait for completion.",
        )

    if not result_file.exists():
        raise HTTPException(status_code=404, detail="Result not found")

    try:
        with open(result_file, "r") as f:
            result_data = json.load(f)
    except Exception as e:
        logger.error("Error reading result: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read result")

    matching_block = result_data.get("matching_erp")
    if matching_block is None:
        raise HTTPException(
            status_code=404,
            detail="No matching data for this job (matching may be disabled or job ran before matching was added).",
        )

    return MatchingERPResult(**matching_block)


@router.get("/{job_id}/workflow", response_model=OperationsWorkflowBlock)
async def get_document_workflow(job_id: str, _user=Depends(get_current_user)):
    """
    Get Operations & Workflow result for a document (exception, queue, approval summary).
    Returns the same data as the `operations_workflow` field in GET /documents/{job_id}/result.
    """
    result_file = UPLOADS_DIR / f"{job_id}_result.json"
    status_file = UPLOADS_DIR / f"{job_id}_status.json"

    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
    except Exception as e:
        logger.error("Error reading status: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read status")

    status = status_data.get("status", "pending")
    if status != DocumentStatus.COMPLETED.value and status != DocumentStatus.COMPLETED:
        raise HTTPException(
            status_code=404,
            detail=f"Workflow not available (job status: {status}). Process the document first and wait for completion.",
        )

    if not result_file.exists():
        raise HTTPException(status_code=404, detail="Result not found")

    try:
        with open(result_file, "r") as f:
            result_data = json.load(f)
    except Exception as e:
        logger.error("Error reading result: %s", e)
        raise HTTPException(status_code=500, detail="Failed to read result")

    workflow_block = result_data.get("operations_workflow")
    if workflow_block is None:
        raise HTTPException(
            status_code=404,
            detail="No workflow data for this job (operations workflow may be disabled or job ran before it was added).",
        )

    return OperationsWorkflowBlock(**workflow_block)


@router.get("/{job_id}/file")
async def get_document_file(job_id: str, _user=Depends(get_current_user)):
    """Serve the raw uploaded file for this job (PDF or image) for browser preview/download."""
    status_file = UPLOADS_DIR / f"{job_id}_status.json"
    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")

    # Find the uploaded file — try each supported extension
    supported = ["pdf", "png", "jpg", "jpeg", "tiff", "tif", "txt"]
    found_path: Path | None = None
    for ext in supported:
        candidate = UPLOADS_DIR / f"{job_id}.{ext}"
        if candidate.exists():
            found_path = candidate
            break

    if not found_path:
        raise HTTPException(status_code=404, detail="File not found for this job")

    # Determine MIME type
    mime, _ = mimetypes.guess_type(str(found_path))
    if not mime:
        mime = "application/octet-stream"

    # Get original filename from status file for content-disposition
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
        original_filename = status_data.get("filename", found_path.name)
    except Exception:
        original_filename = found_path.name

    return FileResponse(
        path=str(found_path),
        media_type=mime,
        filename=original_filename,
        headers={"Content-Disposition": f"inline; filename=\"{original_filename}\""},
    )