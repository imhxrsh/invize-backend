LayoutLM Integration Guide

Overview
- Adds optional LayoutLMv3-based entity detection to the extraction pipeline.
- Consumes per-page images from OCR, runs token classification, and surfaces entity hints.
- Current scaffold enriches rule-based extraction; full text span decoding can be added next.

Dependencies
- Install: `transformers`, `torch`, `timm`, `pillow`
- Torch install tips (Windows):
  - CPU-only: `pip install torch`
  - CUDA 12.1 (example): `pip install --index-url https://download.pytorch.org/whl/cu121 torch`
- Ensure `tesseract` is installed for OCR if not already.

Configuration
- `USE_LAYOUTLM` (env or config.py): enable/disable LayoutLM integration (`true`/`false`).
- `LAYOUTLM_MODEL`: HuggingFace model name (default `microsoft/layoutlmv3-base` or a fine-tuned variant).
- `LAYOUTLM_DEVICE`: `auto`, `cuda`, or `cpu`.
- `LAYOUTLM_CONFIDENCE_THRESHOLD`: minimum score to keep predicted tokens.

How It Works
- OCR now provides `image_paths` and `page_results` per job.
- When `USE_LAYOUTLM=true`, the extractor loads the model and predicts entities per page.
- Results are merged with rule-based extraction; hints and raw entities are stored under `additional_fields`:
  - `additional_fields.layoutlm_entities`: list of `{page, entities: [{label, score}]}`.
  - Hint flags like `date_hint`, `total_hint` may be set to guide fallback extractors.

API Behavior
- No API changes required. The `/documents/{job_id}/result` shape remains the same.
- Look for enriched `additional_fields` and `extracted_data` if hints allow better fallback extraction.

Enabling
1) Add dependencies: `pip install transformers timm pillow` and an appropriate `torch` build.
2) Set environment:
   - `USE_LAYOUTLM=true`
   - Optional: `LAYOUTLM_MODEL=microsoft/layoutlmv3-base`
   - Optional: `LAYOUTLM_DEVICE=auto`
3) Restart the server and upload a PDF in Swagger UI.
4) Fetch result: `GET /documents/{job_id}/result` and check `additional_fields.layoutlm_entities`.

Limitations & Next Steps
- Current engine records labels and scores but does not decode exact text spans/bboxes.
- Improve mapping by aggregating contiguous tokens and extracting text spans.
- Prefer a fine-tuned invoice model (SROIE/DocLayNet) for higher accuracy.
- Add evaluation and confidence-weighted merging with rule-based values.