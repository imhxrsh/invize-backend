"""
FastAPI router for Document Intelligence Agent
"""

import uuid
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from .models import (
    DocumentUploadResponse, 
    DocumentStatusResponse, 
    DocumentResultResponse,
    DocumentStatus
)
from .config import UPLOADS_DIR, MAX_FILE_SIZE_MB, SUPPORTED_FORMATS
from .processor import DocumentProcessor

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Document Intelligence"])
processor = DocumentProcessor()


@router.post("/", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
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
async def get_document_status(job_id: str):
    """Get processing status of a document"""
    
    status_file = UPLOADS_DIR / f"{job_id}_status.json"
    
    if not status_file.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    
    try:
        with open(status_file, "r") as f:
            status_data = json.load(f)
        
        return DocumentStatusResponse(
            job_id=job_id,
            status=status_data.get("status", DocumentStatus.PENDING),
            progress=status_data.get("progress"),
            error=status_data.get("error")
        )
        
    except Exception as e:
        logger.error(f"Error reading status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to read status")


@router.get("/{job_id}/result", response_model=DocumentResultResponse)
async def get_document_result(job_id: str):
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
    
    if status == DocumentStatus.PENDING or status == DocumentStatus.PROCESSING:
        return DocumentResultResponse(
            job_id=job_id,
            status=status,
            error=None
        )
    
    if status == DocumentStatus.FAILED:
        return DocumentResultResponse(
            job_id=job_id,
            status=status,
            error=status_data.get("error", "Processing failed")
        )
    
    # Read result if completed
    if not result_file.exists():
        return DocumentResultResponse(
            job_id=job_id,
            status=DocumentStatus.FAILED,
            error="Result file not found"
        )
    
    try:
        with open(result_file, "r") as f:
            result_data = json.load(f)
        
        return DocumentResultResponse(**result_data)
        
    except Exception as e:
        logger.error(f"Error reading result: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to read result")