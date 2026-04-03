"""
LayoutLMv3 Engine for token classification inference.

This module loads a HuggingFace LayoutLMv3 model and processor and
produces entity predictions from document images. It supports 
token-classification tasks (e.g., SROIE-style invoice fields).

Requirements: transformers, timm, torch, pillow.
"""

import logging
from typing import Dict, List, Any, Optional

import os

logger = logging.getLogger(__name__)


class LayoutLMEngine:
    def __init__(self, model_name: str, device_pref: str = "auto", confidence_threshold: float = 0.5):
        self.model_name = model_name
        self.device_pref = device_pref
        self.confidence_threshold = confidence_threshold
        self._model = None
        self._processor = None
        self._device = "cpu"

    def _ensure_loaded(self):
        if self._model is not None and self._processor is not None:
            return
        try:
            import torch
            from transformers import AutoProcessor, AutoModelForTokenClassification

            # Device selection
            if self.device_pref == "cuda":
                self._device = "cuda" if torch.cuda.is_available() else "cpu"
            elif self.device_pref == "cpu":
                self._device = "cpu"
            else:
                self._device = "cuda" if torch.cuda.is_available() else "cpu"

            self._processor = AutoProcessor.from_pretrained(self.model_name)
            self._model = AutoModelForTokenClassification.from_pretrained(self.model_name)
            self._model.to(self._device)
            self._model.eval()

            logger.info(f"Loaded LayoutLM model '{self.model_name}' on device '{self._device}'")
        except Exception as e:
            logger.warning(f"Failed to load LayoutLM engine: {e}")
            self._model = None
            self._processor = None

    def predict_entities(self, image_paths: List[str]) -> List[Dict[str, Any]]:
        """Run token classification on images and return predicted entities per page.

        Returns a list of dicts: {page, entities: [{label, text, score, bbox}]}
        """
        self._ensure_loaded()
        if self._model is None or self._processor is None:
            return []

        import torch
        from PIL import Image

        id2label = self._model.config.id2label
        results: List[Dict[str, Any]] = []

        for idx, p in enumerate(image_paths):
            try:
                image = Image.open(p).convert("RGB")
                # Use processor's built-in OCR to align words/boxes
                encoded_inputs = self._processor(image, return_tensors="pt", apply_ocr=True)
                encoded_inputs = {k: v.to(self._device) for k, v in encoded_inputs.items()}

                with torch.no_grad():
                    outputs = self._model(**encoded_inputs)
                    logits = outputs.logits  # (batch, seq_len, num_labels)
                    probs = torch.nn.functional.softmax(logits, dim=-1)
                    scores, preds = torch.max(probs, dim=-1)  # (batch, seq_len)

                # Decode entities from predictions; processor provides word-level alignment
                entities = []
                # If processor returns word_ids and boxes
                word_ids = encoded_inputs.get("word_ids", None)
                # word_ids is not a tensor; processor returns a list from its internal OCR; we reconstruct using tokenizer mapping
                # Fallback: iterate over sequence tokens and map to labels
                seq_len = preds.shape[1]
                for i in range(seq_len):
                    label_id = int(preds[0, i].item())
                    score = float(scores[0, i].item())
                    label = id2label.get(label_id, str(label_id))
                    if score >= self.confidence_threshold:
                        entities.append({
                            "label": label,
                            "score": score
                        })

                results.append({
                    "page": idx + 1,
                    "entities": entities
                })

            except Exception as e:
                logger.warning(f"LayoutLM inference failed on page {idx+1}: {e}")
                results.append({"page": idx + 1, "entities": []})

        return results

    @property
    def device(self) -> str:
        return self._device

    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._processor is not None

    @staticmethod
    def map_entities_to_fields(entity_pages: List[Dict[str, Any]], page_texts: Optional[List[str]] = None) -> Dict[str, Any]:
        """Heuristic mapping from common invoice labels (SROIE-style) to our fields.

        Known labels: COMPANY, DATE, ADDRESS, TOTAL (case-insensitive).
        """
        fields: Dict[str, Any] = {}
        def set_if_missing(k: str, v: Any):
            if v and not fields.get(k):
                fields[k] = v

        # Join entity texts if available in page_texts; otherwise use label presence as flags
        # Since we didn't decode text per entity here, we set fields when labels are present.
        # This is a minimal scaffold; fine-tuned models with proper decoding should provide text spans.
        for page in entity_pages:
            labels_present = [e["label"].upper() for e in page.get("entities", [])]
            # Without spans, we can only set indicators; leave actual values to rule-based fallback
            if "COMPANY" in labels_present:
                # Use page text top lines for supplier
                if page_texts and len(page_texts) >= page["page"]:
                    top = page_texts[page["page"] - 1].splitlines()[:5]
                    set_if_missing("supplier", " ".join(t for t in top if t.strip()))
            if "DATE" in labels_present:
                # defer to rule-based date extraction; set a hint flag
                set_if_missing("date_hint", True)
            if "ADDRESS" in labels_present:
                set_if_missing("supplier_address_hint", True)
            if "TOTAL" in labels_present:
                set_if_missing("total_hint", True)

        return fields