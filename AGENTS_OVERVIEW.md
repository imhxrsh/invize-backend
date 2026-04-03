# Invize Backend — Agents Overview

This document describes the **currently implemented** agents and the document intelligence pipeline. It is aligned with the codebase under `backend/agents/`.

---

## Implemented Agents

### 1. Hello Agent

| Property     | Description                                                                        |
| ------------ | ---------------------------------------------------------------------------------- |
| **Purpose**  | Demo / health check for the Swarms AI integration.                                 |
| **Module**   | `agents/hello_agent.py`                                                            |
| **Endpoint** | `GET /agent/hello`                                                                 |
| **Tech**     | [Swarms](https://github.com/kyegomez/swarms) `Agent` with a minimal system prompt. |

Returns a “Hello World”–style response from the Swarms runtime. Used to verify that the agent stack is available before calling document intelligence.

---

### 2. Document Intelligence Agent

| Property         | Description                                                                                          |
| ---------------- | ---------------------------------------------------------------------------------------------------- |
| **Purpose**      | End-to-end invoice/document processing: OCR → field extraction → validation → optional LLM analysis. |
| **Module**       | `agents/document_intelligence/`                                                                      |
| **Orchestrator** | `DocumentProcessor` in `processor.py`                                                                |
| **API**          | Mounted under the document-intelligence router (see `main.py`).                                      |

Single pipeline that runs in order:

1. **OCR** — `OCRProcessor` (`ocr.py`): Tesseract + OpenCV preprocessing; supports PDF (text extraction + conversion to images) and images.
2. **Field extraction** — `FieldExtractor` (`extractor.py`): Optional LayoutLMv3/LILT via `LayoutLMEngine`; regex-based fallbacks for invoice number, dates, totals, line items, etc.
3. **Validation & normalization** — `_validate_and_normalize()` in `DocumentProcessor`: document type and field cleanup.
4. **Optional Swarms analysis** — `_analyze_with_swarms()`: passes extracted data to a Swarms `Agent` (Context7) for invoice analysis; failures are logged and do not fail the job.

Result (including `agent_analysis` when Swarms runs) is written to `{job_id}_result.json`; status updates go to `{job_id}_status.json`. After validation, **Verification & Compliance** (Agent 3) runs and its result is merged into the same JSON.

---

### 3. Verification & Compliance Agent

| Property      | Description                                                                                     |
| ------------- | ----------------------------------------------------------------------------------------------- |
| **Purpose**   | Duplicate detection, document quality / authenticity checks, and audit trail for each document. |
| **Module**    | `agents/verification_compliance/`                                                               |
| **Endpoints** | No separate upload; runs inside document pipeline. See **How to use** below.                    |

Runs automatically after Document Intelligence validation (and optional Swarms analysis):

- **Duplicate check** — Fuzzy match (RapidFuzz) on invoice number/amount/date; optional perceptual hash (imagededup); stores fingerprints in `ProcessedDocumentFingerprint`.
- **Authenticity** — OpenCV quality (blur/contrast), rule-based fraud signals; stamp detection placeholder for Phase 2.
- **Audit** — structlog + optional `DocumentAuditEvent` in MongoDB.

Result is written into `result.verification_compliance` (duplicate_check, authenticity, audit_event_ids).

**How to use (FastAPI)**

1. **Upload and process (Verification runs automatically)**  
   `POST /documents/` with a file → returns `job_id`.  
   Processing in the background includes OCR → extraction → validation → (Swarms) → **verification** → write result.

2. **Get full result (includes verification)**  
   `GET /documents/{job_id}/result` → response includes `verification_compliance` with `duplicate_check`, `authenticity`, `audit_event_ids`.

3. **Get only verification data**  
   `GET /documents/{job_id}/verification` → returns just the verification block (404 if job not completed or verification disabled).

4. **Poll status**  
   `GET /documents/{job_id}/status` → use until `status` is `completed`, then fetch result or verification.

---

## Pipeline Summary

```
Upload → DocumentProcessor
           ├── OCRProcessor (Tesseract, PDF/images)
           ├── FieldExtractor (LayoutLMv3 + regex)
           ├── _validate_and_normalize()
           ├── _analyze_with_swarms() [optional]
           ├── run_verification() [Verification & Compliance]
           └── write result + status JSON
```

---

## Key Files

| Role                      | Path                                                                                |
| ------------------------- | ----------------------------------------------------------------------------------- |
| Hello agent               | `agents/hello_agent.py`                                                             |
| Doc intelligence router   | `agents/document_intelligence/api.py`                                               |
| Pipeline orchestration    | `agents/document_intelligence/processor.py`                                         |
| OCR                       | `agents/document_intelligence/ocr.py`                                               |
| Field extraction          | `agents/document_intelligence/extractor.py`                                         |
| LayoutLM integration      | `agents/document_intelligence/layoutlm_engine.py`                                   |
| Verification & Compliance | `agents/verification_compliance/` (processor, audit, duplicate_check, authenticity) |
| Config & models           | `agents/document_intelligence/config.py`, `models.py`                               |

---

## Planned Agents (Future Implementation)

The following **three** agents are planned; Verification & Compliance (Agent 3) is already implemented.

### 4. Matching & ERP Agent

**Status: Partially implemented (demo).** Implemented with **dummy ERP data** (templates for PO, GRN, vendor) for end-to-end demo. **Tally** and **SAP** connectors to be built later and plugged in via the same adapter interface.

| Responsibility      | Details                                                                                                                                              |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **PO matching**     | Match invoices to Purchase Orders in ERP; 3-way matching (PO → GRN → Invoice); price/quantity variance detection; tax-calculation validation.        |
| **ERP integration** | API integration with ERP systems (SAP, Oracle, Tally, etc.); real-time vendor master and GL code validation; posting and approval-workflow triggers. |

_Merges: PO Matching & Validation, ERP Integration._

---

### 5. Operations & Workflow Agent

| Responsibility      | Details                                                                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Exceptions**      | Classify exceptions (missing PO, price mismatch, validation failures); route to review queues; suggest resolutions from history; escalation workflows. |
| **Approvals**       | Route by approval hierarchy; multi-level approvals; track status and SLA; reminders and notifications.                                                 |
| **Dashboard & ops** | Aggregate data for dashboards; analytics and KPIs (cycle time, accuracy, cost savings); review-queue prioritization.                                   |

_Merges: Exception Handling, Approval Workflow, Dashboard Orchestrator._

---

### 6. Quality & Learning Agent

| Responsibility        | Details                                                                                                                 |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| **Quality assurance** | Monitor extraction accuracy; A/B test model versions; flag invoices for human review; confidence and accuracy reports.  |
| **Learning**          | Collect reviewer feedback; fine-tune models and update validation rules from exceptions; synthetic data for edge cases. |

_Merges: Quality Assurance, Learning & Adaptation._

---

## Summary

| #   | Agent                           | Status                       |
| --- | ------------------------------- | ---------------------------- |
| 1   | Hello Agent                     | Implemented                  |
| 2   | Document Intelligence Agent     | Implemented                  |
| 3   | Verification & Compliance Agent | Implemented                  |
| 4   | Matching & ERP Agent            | Partially implemented (demo) |
| 5   | Operations & Workflow Agent     | Planned                      |
| 6   | Quality & Learning Agent        | Planned                      |

Current codebase implements **1**, **2**, and **3**. Agent **4** is planned with **dummy/demo ERP data** (templates for PO, GRN, vendor) for demo; **Tally** and **SAP** connectors to be built later.
