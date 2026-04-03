# Document Intelligence Agent - Prototype

A rapid prototype implementation of Agent 1.1 from the AGENTS_OVERVIEW.md - Document Intelligence Agent that orchestrates OCR and document understanding for invoice processing.

## Features

- **Document Upload**: Accepts PDF, PNG, JPG, JPEG, TIFF files up to 50MB
- **OCR Processing**: Uses Tesseract with OpenCV preprocessing (deskew, denoise, threshold)
- **Field Extraction**: Rule-based extraction of invoice fields with table detection
- **Document Classification**: Automatic classification as structured/semi-structured/unstructured
- **Local Storage**: Files stored in `agent_workspace/uploads/` and `agent_workspace/temp/`
- **Async Processing**: Background processing with status tracking

## API Endpoints

### Upload Document
```
POST /documents
Content-Type: multipart/form-data

Response:
{
  "job_id": "uuid",
  "status": "pending",
  "message": "Document uploaded successfully. Processing started."
}
```

### Check Status
```
GET /documents/{job_id}/status

Response:
{
  "job_id": "uuid",
  "status": "processing|completed|failed",
  "progress": "Current processing step",
  "error": "Error message if failed"
}
```

### Get Results
```
GET /documents/{job_id}/result

Response:
{
  "job_id": "uuid",
  "status": "completed",
  "document_type": "structured|semi_structured|unstructured",
  "extracted_data": {
    "supplier": "Company Name",
    "supplier_address": "Street, City, Country",
    "supplier_tax_id": "TIN/GST/VAT",
    "supplier_email": "billing@vendor.com",
    "supplier_phone": "+1-555-0000",
    "invoice_number": "INV-2024-001",
    "date": "01/15/2024",
    "due_date": "02/15/2024",
    "currency": "USD",
    "currency_symbol": "$",
    "subtotal": 35.00,
    "tax": 3.50,
    "tax_rate": 10.0,
    "discount": 0.0,
    "shipping": 0.0,
    "handling": 0.0,
    "other_charges": 0.0,
    "total": 38.50,
    "po_number": "PO-7788",
    "payment_terms": "Net 30",
    "bill_to": "Buyer Corp\n123 Road\nCity",
    "ship_to": "Buyer Warehouse\nCity",
    "buyer": "Buyer Corp",
    "gstin": null,
    "vat_id": "GB123456789",
    "pan": null,
    "bank_account": "123456-01",
    "iban": "GB82WEST12345698765432",
    "swift": "ABCDEFXX",
    "notes": "Thank you",
    "line_items": [
      {
        "description": "Widget A",
        "quantity": 2.0,
        "unit_price": 10.00,
        "amount": 20.00,
        "confidence": 0.85,
        "item_code": "SKU-1001",
        "tax_rate": 10.0
      }
    ],
    "confidence": 0.82
  },
  "processing_time": 2.45,
  "raw_text": "Full OCR text...",
  "additional_fields": {"reference": "ABC-123", "department": "Finance"},
  "agent_analysis": {
    "context": "Context7",
    "model": "openai/gpt-oss-20b",
    "result": "{\"summary\":\"...\",\"flags\":[\"possible duplicate\"],\"recommendations\":[\"verify PO\"]}",
    "execution_time": 1.23
  }
}
```

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   FastAPI       │    │   Document       │    │   OCR           │
│   Endpoints     │───▶│   Processor      │───▶│   Processor     │
│                 │    │                  │    │   (Tesseract)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │                        │
                                ▼                        ▼
                       ┌──────────────────┐    ┌─────────────────┐
                       │   Field          │    │   OpenCV        │
                       │   Extractor      │    │   Preprocessing │
                       │   (Rule-based)   │    │                 │
                       └──────────────────┘    └─────────────────┘
```

## File Structure

```
agents/document_intelligence/
├── __init__.py          # Package initialization
├── api.py              # FastAPI router with endpoints
├── config.py           # Configuration using dotenv
├── models.py           # Pydantic data models
├── processor.py        # Main orchestration logic
├── ocr.py             # Tesseract OCR with preprocessing
└── extractor.py       # Rule-based field extraction
```

## Dependencies Required

The prototype requires these additional packages in requirements.txt:
```
opencv-python
pytesseract
pdf2image
pillow
```

## Setup

1. **Install Tesseract OCR**:
   - Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki
   - Add to PATH or set `pytesseract.pytesseract.tesseract_cmd` in `ocr.py`

2. **Environment Variables** (optional):
   ```
   REDIS_URL=redis://localhost:6379/0
   MAX_FILE_SIZE_MB=50
   TESSERACT_LANGS=eng
   PSM_DEFAULT=6
   PDF_DPI=300
   LOG_LEVEL=INFO
   ```

3. **Directory Structure**:
   The agent automatically creates:
   - `agent_workspace/uploads/` - Permanent file storage
   - `agent_workspace/temp/` - Temporary processing files

## Testing

Run the test script:
```bash
python test_document_intelligence.py
```

This will:
1. Upload a test document
2. Monitor processing status
3. Display extracted results

## Current Limitations

- **Rule-based extraction only**: LayoutLMv3 integration is placeholder
- **Improved but heuristic table detection**: Header/column heuristics for line items
- **No Celery**: Uses FastAPI BackgroundTasks instead
- **Text files supported**: For testing without OCR dependencies
- **Simple validation**: Basic numeric parsing and normalization

## Future Enhancements

1. **LayoutLMv3 Integration**: Replace rule-based extraction
2. **Celery Task Queue**: For better scalability and monitoring
3. **Advanced Preprocessing**: Better deskewing and noise reduction
4. **Table Structure Recognition**: Improved line item extraction
5. **Confidence Scoring**: ML-based confidence calculation
6. **Multi-language Support**: Extended language packs

## Usage Example

```python
import requests

# Upload document
with open("invoice.pdf", "rb") as f:
    response = requests.post(
        "http://localhost:8000/documents",
        files={"file": f}
    )

job_id = response.json()["job_id"]

# Check status
status = requests.get(f"http://localhost:8000/documents/{job_id}/status")

# Get results when completed
result = requests.get(f"http://localhost:8000/documents/{job_id}/result")
extracted_data = result.json()["extracted_data"]
```

## Error Handling

- **File validation**: Size limits, format checking
- **OCR failures**: Graceful degradation with error messages
- **Processing errors**: Detailed error reporting in status
- **Timeout handling**: Background task monitoring

This prototype provides a working foundation for document intelligence that can be extended with more sophisticated ML models and processing capabilities.