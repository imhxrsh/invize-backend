1. Core Processing Agents
   1.1 Document Intelligence Agent - Orchestrates OCR and document understanding - Routes invoices based on type/format (structured, semi-structured, unstructured) - Handles pre-processing (image enhancement, rotation correction, noise reduction) - Coordinates with LayoutLMv3/LILT models

   1.2 Field Extraction Agent - Extracts header-level data (vendor details, invoice number, dates, totals) - Extracts line-item data (product codes, quantities, prices, taxes) - Handles multi-layout and template-free extraction - Manages confidence scoring for extracted fields

   1.3 Authenticity Verification Agent - Stamp detection and validation using RetinaNet - Signature detection and verification - Document quality assessment - Fraud pattern detection

   1.4 Duplicate Detection Agent - Checks against historical invoice database - Fuzzy matching on invoice numbers, amounts, dates - Hash-based similarity detection - Cross-vendor duplicate identification

   1.5 PO Matching & Validation Agent - Matches invoices with Purchase Orders in ERP - 3-way matching (PO → GRN → Invoice) - Price and quantity variance detection - Tax calculation validation

   1.6 ERP Integration Agent - Manages API calls to ERP systems (SAP, Oracle, Tally, etc.) - Real-time vendor master data lookup - GL code validation - Posting and approval workflow triggers

2. Orchestration & Intelligence Agents
   2.1 Exception Handling Agent - Classifies exceptions (missing PO, price mismatch, failed validation) - Routes to appropriate review queues - Suggests resolutions based on historical patterns - Manages escalation workflows

   2.2 Quality Assurance Agent - Continuous monitoring of extraction accuracy - A/B testing of model versions - Identifies invoices needing human review - Generates confidence reports

   2.3 Learning & Adaptation Agent - Collects feedback from human reviewers - Fine-tunes models with new data patterns - Updates validation rules based on exceptions - Manages synthetic data generation for edge cases

3. User Interface Agents
   3.1 Dashboard Orchestrator Agent - Aggregates data for real-time dashboard - Generates analytics and KPIs (cycle time, accuracy, cost savings) - Manages user notifications and alerts - Coordinates review queue prioritization

   3.2 Approval Workflow Agent - Routes invoices based on approval hierarchies - Manages multi-level approvals - Tracks approval status and SLA compliance - Sends reminders and notifications

4. Support Agents
   4.1 Audit Trail Agent - Logs all processing steps and decisions - Maintains version history of document states - Generates compliance reports - Supports forensic analysis
