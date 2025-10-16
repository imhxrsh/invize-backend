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

logger = logging.getLogger(__name__)


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

            # Step 4: Optional Swarms agent analysis (Context7)
            self._update_status(job_id, DocumentStatus.PROCESSING, "Analyzing with agent...")
            try:
                analysis = self._analyze_with_swarms(
                    validated_data.get("extracted_data", {}),
                    validated_data.get("additional_fields", {})
                )
            except Exception:
                analysis = None
            
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
                "agent_analysis": analysis
            }
            
            result_file = UPLOADS_DIR / f"{job_id}_result.json"
            with open(result_file, "w") as f:
                json.dump(result, f, indent=2, default=str)
            
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
        """Pass extracted data to a Swarms agent for analysis using Context7."""
        try:
            from swarms import Agent
        except Exception as e:
            logger.warning(f"Swarms unavailable: {e}")
            return None

        import os, json, time
        context_name = os.getenv("ANALYSIS_CONTEXT", "Context7")
        model_name = os.getenv("AGENT_MODEL_NAME", "openai/gpt-oss-20b")
        system_prompt = (
            f"You are an invoice analysis agent operating under {context_name}. "
            "Analyze the provided invoice JSON for completeness, anomalies, currency correctness, "
            "tax validation, PO matching hints, and summarize key fields and any issues. "
            "Respond with a concise JSON: {summary, flags[], recommendations[]}."
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
            result = agent.run(task=f"Analyze this invoice: {json.dumps(payload)}")
            duration = time.time() - start
            return {
                "context": context_name,
                "model": model_name,
                "result": str(result),
                "execution_time": duration,
            }
        except Exception as e:
            logger.warning(f"Agent analysis failed: {e}")
            return None