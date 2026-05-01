"""
Document Processor - Main orchestration logic
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

from .config import UPLOADS_DIR, TEMP_DIR
from .models import DocumentStatus, DocumentType, ExtractedData, LineItem
from .ocr import OCRProcessor
from .extractor import FieldExtractor
from agents.swarms_model_name import get_swarms_model_name

logger = logging.getLogger(__name__)

_PROGRESS_HISTORY_CAP = 100


class DocumentProcessor:
    """Main document processing orchestrator"""
    
    def __init__(self):
        self.ocr_processor = OCRProcessor()
        self.field_extractor = FieldExtractor()
    
    async def process_document(self, job_id: str, file_path: Path):
        """Process a document through the complete pipeline"""
        
        start_time = time.time()
        
        try:
            # Update status to processing
            self._update_status(job_id, DocumentStatus.PROCESSING, "Starting processing...")
            
            # Step 1: OCR Processing
            self._update_status(job_id, DocumentStatus.PROCESSING, "Performing OCR...")
            ocr_result = await self.ocr_processor.process(file_path, job_id)
            
            if not ocr_result:
                raise Exception("OCR processing failed")
            
            # Step 2: Document Classification & Field Extraction
            self._update_status(job_id, DocumentStatus.PROCESSING, "Extracting fields...")
            extracted_data = await self.field_extractor.extract(ocr_result, job_id)
            
            # Step 3: Validation & Post-processing
            self._update_status(job_id, DocumentStatus.PROCESSING, "Validating results...")
            validated_data = self._validate_and_normalize(extracted_data)

            # Step 3b: Optional Groq JSON fill for missing totals / invoice # (Context7 groq-python)
            self._update_status(job_id, DocumentStatus.PROCESSING, "Enriching fields (optional LLM)...")
            raw_for_groq = validated_data.get("raw_text") or ""
            if not raw_for_groq and ocr_result:
                raw_for_groq = ocr_result.get("full_text") or ""
            try:
                from .groq_extract import enrich_extracted_with_groq
                validated_data["extracted_data"] = await enrich_extracted_with_groq(
                    validated_data["extracted_data"],
                    raw_for_groq or None,
                    job_id,
                )
            except Exception as e:
                logger.warning("Groq extraction enrich skipped for job %s: %s", job_id, e)

            # Step 4: Optional Swarms agent analysis (Context7)
            self._update_status(job_id, DocumentStatus.PROCESSING, "Analyzing with agent...")
            try:
                analysis = self._analyze_with_swarms(
                    validated_data.get("extracted_data", {}),
                    validated_data.get("additional_fields", {})
                )
            except Exception:
                analysis = None

            # Step 5: Verification & Compliance (optional)
            self._update_status(
                job_id,
                DocumentStatus.PROCESSING,
                "Running verification and compliance checks...",
            )
            verification_compliance = {}
            try:
                from agents.verification_compliance.processor import run_verification
                verification_compliance = await run_verification(job_id, file_path, validated_data)
            except Exception as e:
                logger.warning("Verification agent skipped or failed: %s", e)

            # Step 6: Matching & ERP (optional, demo data; Tally/SAP later)
            self._update_status(
                job_id,
                DocumentStatus.PROCESSING,
                "Matching to purchase orders and vendor records...",
            )
            matching_erp_result = {}
            try:
                from agents.matching_erp.processor import run_matching_erp
                matching_erp_result = await run_matching_erp(job_id, validated_data)
            except Exception as e:
                logger.warning("Matching & ERP agent skipped or failed: %s", e)
            
            # Calculate processing time
            processing_time = time.time() - start_time
            
            # Save final result
            result = {
                "job_id": job_id,
                "status": DocumentStatus.COMPLETED.value,  # Use .value to get string
                "document_type": validated_data.get("document_type", DocumentType.UNSTRUCTURED.value),
                "extracted_data": validated_data.get("extracted_data", {}),
                "processing_time": processing_time,
                "raw_text": validated_data.get("raw_text"),
                "additional_fields": validated_data.get("additional_fields"),
                "agent_analysis": analysis,
                "verification_compliance": verification_compliance or None,
                "matching_erp": matching_erp_result or None,
            }
            
            result_file = UPLOADS_DIR / f"{job_id}_result.json"
            with open(result_file, "w") as f:
                json.dump(result, f, indent=2, default=str)
            
            # Operations & Workflow (optional): classify exception, create queue/approval, merge block
            self._update_status(
                job_id,
                DocumentStatus.PROCESSING,
                "Applying operations workflow (queues and approvals)...",
            )
            try:
                from agents.operations_workflow.processor import run_operations_workflow
                ops_block = await run_operations_workflow(job_id, result)
                if ops_block:
                    result["operations_workflow"] = ops_block
                    with open(result_file, "w") as f:
                        json.dump(result, f, indent=2, default=str)
            except Exception as e:
                logger.warning("Operations workflow agent skipped or failed: %s", e)
            
            # Update final status
            self._update_status(job_id, DocumentStatus.COMPLETED, "Processing completed")
            
            logger.info(f"Document {job_id} processed successfully in {processing_time:.2f}s")
            
        except Exception as e:
            logger.error(f"Error processing document {job_id}: {str(e)}")
            self._update_status(job_id, DocumentStatus.FAILED, f"Processing failed: {str(e)}")
    
    def _update_status(self, job_id: str, status: DocumentStatus, progress: Optional[str] = None):
        """Update job status"""
        
        status_file = UPLOADS_DIR / f"{job_id}_status.json"
        
        try:
            # Read existing status
            if status_file.exists():
                with open(status_file, "r") as f:
                    status_data = json.load(f)
            else:
                status_data = {"job_id": job_id}
            
            # Update status - convert enum to string
            status_data["status"] = status.value if hasattr(status, 'value') else str(status)
            if progress:
                status_data["progress"] = progress
                hist = status_data.get("progress_history")
                if not isinstance(hist, list):
                    hist = []
                if not hist or hist[-1] != progress:
                    hist.append(progress)
                if len(hist) > _PROGRESS_HISTORY_CAP:
                    hist = hist[-_PROGRESS_HISTORY_CAP:]
                status_data["progress_history"] = hist
            
            # Write back
            with open(status_file, "w") as f:
                json.dump(status_data, f)
                
        except Exception as e:
            logger.error(f"Error updating status for {job_id}: {str(e)}")
    
    def _validate_and_normalize(self, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize extracted data"""
        
        # Basic validation and normalization
        validated = {
            "document_type": extracted_data.get("document_type", DocumentType.UNSTRUCTURED).value if hasattr(extracted_data.get("document_type", DocumentType.UNSTRUCTURED), 'value') else str(extracted_data.get("document_type", DocumentType.UNSTRUCTURED)),
            "extracted_data": {},
            "additional_fields": extracted_data.get("extracted_data", {}).get("additional_fields"),
            "raw_text": extracted_data.get("extracted_data", {}).get("raw_text")
        }
        
        data = extracted_data.get("extracted_data", {})
        
        # Normalize numeric fields
        for field in [
            "subtotal", "tax", "total", "discount", "shipping", "handling", "other_charges", "exchange_rate", "tax_rate"
        ]:
            if field in data and data[field]:
                try:
                    validated["extracted_data"][field] = float(str(data[field]).replace(",", "").replace("$", ""))
                except (ValueError, TypeError):
                    validated["extracted_data"][field] = None
        
        # Copy string fields
        for field in [
            "supplier", "supplier_address", "supplier_tax_id", "supplier_email", "supplier_phone",
            "invoice_number", "date", "due_date", "currency", "currency_symbol",
            "po_number", "payment_terms", "bill_to", "ship_to", "buyer",
            "gstin", "vat_id", "pan", "bank_account", "ifsc", "iban", "swift", "notes"
        ]:
            validated["extracted_data"][field] = data.get(field)
        
        # Process line items
        line_items = data.get("line_items", [])
        validated_items = []
        
        for item in line_items:
            validated_item = {}
            validated_item["description"] = item.get("description")
            
            # Normalize numeric fields in line items
            for num_field in ["quantity", "unit_price", "amount", "tax_rate", "tax_amount"]:
                if num_field in item and item[num_field]:
                    try:
                        validated_item[num_field] = float(str(item[num_field]).replace(",", "").replace("$", ""))
                    except (ValueError, TypeError):
                        validated_item[num_field] = None
                else:
                    validated_item[num_field] = None

            validated_item["confidence"] = item.get("confidence", 0.0)
            validated_item["item_code"] = item.get("item_code")
            validated_items.append(validated_item)
        
        validated["extracted_data"]["line_items"] = validated_items
        
        # Calculate overall confidence
        confidences = [item.get("confidence", 0.0) for item in validated_items if item.get("confidence")]
        if confidences:
            validated["extracted_data"]["confidence"] = sum(confidences) / len(confidences)
        else:
            validated["extracted_data"]["confidence"] = 0.5  # Default confidence

        return validated

    def _analyze_with_swarms(self, extracted: Dict[str, Any], additional: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Pass extracted data to a Swarms agent; return validated JSON in result (never trust raw model text)."""
        try:
            from swarms import Agent
        except Exception as e:
            logger.warning(f"Swarms unavailable: {e}")
            return None

        import os, json, time

        from agents.agent_output_validate import (
            invoice_analysis_retry_task,
            merge_invoice_analysis_with_extracted,
            normalize_invoice_analysis_swarms,
            should_retry_swarms_json,
        )

        context_name = os.getenv("ANALYSIS_CONTEXT", "Context7")
        model_name = get_swarms_model_name()
        system_prompt = (
            f"You are an invoice analysis agent ({context_name}). "
            "Input is JSON with extracted_data (pipeline fields: supplier, buyer, bill_to, amounts, dates, line_items, …) "
            "and optional additional_fields. "
            "You must only infer supplier_guess and buyer_guess from that payload—never invent names or numbers not grounded in it. "
            "If unsure, use null for guesses and say so in summary. "
            "Tasks: (1) supplier_guess = issuer of the tax invoice; buyer_guess = bill-to/customer. "
            "(2) Flag swapped supplier/buyer, missing vendor, or totals that do not reconcile (subtotal + tax vs total). "
            "(3) Note missing invoice_number, due_date, currency mismatch, or PO when visible in payload. "
            "(4) recommendations: max 8 actionable AP checks; flags: max 8 short issues. "
            "summary: 2–4 neutral sentences. "
            "Output one JSON object only—no markdown fences, no extra keys. "
            "Keys exactly: summary (string), supplier_guess (string|null), buyer_guess (string|null), "
            "flags (string[]), recommendations (string[])."
        )

        agent = Agent(
            agent_name="Invoice-Analysis-Agent",
            agent_description="Analyzes invoice details for clearance automation",
            system_prompt=system_prompt,
            model_name=model_name,
            max_loops=1,
            output_type="str",
            dynamic_temperature_enabled=False,
        )

        payload = {
            "extracted_data": extracted,
            "additional_fields": additional,
        }
        start = time.time()
        try:
            result = agent.run(
                task=(
                    "Return one JSON object with the exact keys in your system instructions. "
                    "Do not include markdown code fences. "
                    f"Payload: {json.dumps(payload)}"
                )
            )
            raw_text = str(result).strip()
            normalized = normalize_invoice_analysis_swarms(raw_text)
            if not normalized.get("_meta", {}).get("parse_ok") and should_retry_swarms_json():
                try:
                    result2 = agent.run(
                        task=invoice_analysis_retry_task() + " Payload: " + json.dumps(payload)
                    )
                    normalized = normalize_invoice_analysis_swarms(str(result2).strip())
                except Exception as re:
                    logger.warning("Invoice analysis JSON retry failed: %s", re)
            normalized = merge_invoice_analysis_with_extracted(
                normalized,
                extracted.get("supplier") if isinstance(extracted, dict) else None,
                extracted.get("buyer") if isinstance(extracted, dict) else None,
            )
            duration = time.time() - start
            return {
                "context": context_name,
                "model": model_name,
                "result": json.dumps(normalized, ensure_ascii=False),
                "execution_time": duration,
                "parse_ok": bool(normalized.get("_meta", {}).get("parse_ok")),
            }
        except Exception as e:
            logger.warning(f"Agent analysis failed: {e}")
            return None