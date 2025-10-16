"""
Field Extractor using LayoutLMv3 and rule-based fallbacks
"""

import re
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from .models import DocumentType
try:
    from config import USE_LAYOUTLM, LAYOUTLM_MODEL, LAYOUTLM_DEVICE, LAYOUTLM_CONFIDENCE_THRESHOLD
except ImportError:
    from .config import USE_LAYOUTLM, LAYOUTLM_MODEL, LAYOUTLM_DEVICE, LAYOUTLM_CONFIDENCE_THRESHOLD
from .layoutlm_engine import LayoutLMEngine

logger = logging.getLogger(__name__)


class FieldExtractor:
    """Extracts structured fields from OCR results"""
    
    def __init__(self):
        # Toggle LayoutLM integration via env/config
        self.use_layoutlm = bool(USE_LAYOUTLM)
        self._layoutlm: Optional[LayoutLMEngine] = None
        
        # Common patterns for invoice fields
        self.patterns = {
            'invoice_number': [
                r'invoice\s*(no\.|number|#)?\s*:?\s*([A-Z0-9\-]+)',
                r'inv\s*(no\.|number|#)?\s*:?\s*([A-Z0-9\-]+)',
                r'bill\s*(no\.|number|#)?\s*:?\s*([A-Z0-9\-]+)',
                r'invoice\s*id\s*:?\s*([A-Z0-9\-]+)',
                r'\bINV\-?\s*([A-Z0-9\-]+)',
                r'#\s*([A-Z0-9\-]+)'
            ],
            'date': [
                r'date\s*:?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
                r'invoice\s*date\s*:?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
                r'(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
                r'((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})'
            ],
            'due_date': [
                r'due\s*date\s*:?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
                r'payment\s*due\s*:?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
                r'due\s*date\s*:?\s*((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4})'
            ],
            'total': [
                r'total\s*:?\s*\$?\s*([0-9,]+\.?\d*)',
                r'amount\s*due\s*:?\s*\$?\s*([0-9,]+\.?\d*)',
                r'grand\s*total\s*:?\s*\$?\s*([0-9,]+\.?\d*)',
                r'total\s*due\s*:?\s*\$?\s*([0-9,]+\.?\d*)'
            ],
            'subtotal': [
                r'subtotal\s*:?\s*\$?\s*([0-9,]+\.?\d*)',
                r'sub\s*total\s*:?\s*\$?\s*([0-9,]+\.?\d*)'
            ],
            'tax': [
                r'tax\s*:?\s*\$?\s*([0-9,]+\.?\d*)',
                r'vat\s*:?\s*\$?\s*([0-9,]+\.?\d*)',
                r'sales\s*tax\s*:?\s*\$?\s*([0-9,]+\.?\d*)'
            ]
        }
    
    async def extract(self, ocr_result: Dict[str, Any], job_id: str) -> Dict[str, Any]:
        """Extract fields from OCR result"""
        
        try:
            # Classify document type
            doc_type = self._classify_document(ocr_result)
            
            # Extract fields based on document type
            if self.use_layoutlm:
                extracted_data = await self._extract_with_layoutlm(ocr_result, doc_type)
            else:
                extracted_data = self._extract_with_rules(ocr_result, doc_type)
            
            return {
                'document_type': doc_type,
                'extracted_data': extracted_data
            }
            
        except Exception as e:
            logger.error(f"Field extraction failed for job {job_id}: {str(e)}")
            return {
                'document_type': DocumentType.UNSTRUCTURED,
                'extracted_data': {}
            }
    
    def _classify_document(self, ocr_result: Dict[str, Any]) -> DocumentType:
        """Classify document type based on OCR content"""
        
        text = ocr_result.get('full_text', '').lower()
        
        # Look for structured indicators
        structured_indicators = [
            'invoice', 'bill', 'receipt', 'statement',
            'total', 'subtotal', 'tax', 'amount due'
        ]
        
        # Count structured elements
        structured_count = sum(1 for indicator in structured_indicators if indicator in text)
        
        # Look for table-like structures
        words = ocr_result.get('all_words', [])
        has_table_structure = self._detect_table_structure(words)
        
        # Classification logic
        if structured_count >= 3 and has_table_structure:
            return DocumentType.STRUCTURED
        elif structured_count >= 2:
            return DocumentType.SEMI_STRUCTURED
        else:
            return DocumentType.UNSTRUCTURED
    
    def _detect_table_structure(self, words: List[Dict[str, Any]]) -> bool:
        """Detect if document has table-like structure"""
        
        if len(words) < 10:
            return False
        
        # Group words by approximate Y coordinate (rows)
        rows = {}
        for word in words:
            y = word['bbox']['y']
            row_key = y // 20  # Group words within 20 pixels vertically
            
            if row_key not in rows:
                rows[row_key] = []
            rows[row_key].append(word)
        
        # Check if we have multiple rows with similar word counts
        row_lengths = [len(row) for row in rows.values()]
        
        if len(row_lengths) < 3:
            return False
        
        # Look for consistent column structure
        avg_length = sum(row_lengths) / len(row_lengths)
        consistent_rows = sum(1 for length in row_lengths if abs(length - avg_length) <= 2)
        
        return consistent_rows >= 3
    
    def _extract_with_rules(self, ocr_result: Dict[str, Any], doc_type: DocumentType) -> Dict[str, Any]:
        """Extract fields using rule-based approach"""
        
        text = ocr_result.get('full_text', '')
        extracted = {}
        
        # Extract supplier (usually at the top)
        extracted['supplier'] = self._extract_supplier(text, ocr_result.get('all_words', []))
        
        # Extract structured fields using patterns
        for field, patterns in self.patterns.items():
            extracted[field] = self._extract_with_patterns(text, patterns)
        
        # Extract line items if table structure detected
        if doc_type in [DocumentType.STRUCTURED, DocumentType.SEMI_STRUCTURED]:
            extracted['line_items'] = self._extract_line_items(ocr_result.get('all_words', []))
        else:
            extracted['line_items'] = []
        
        # Detect currency (ISO code and symbol)
        code, symbol = self._detect_currency_details(text)
        extracted['currency'] = code
        extracted['currency_symbol'] = symbol

        # Extract PO number
        extracted['po_number'] = self._extract_po_number(text)

        # Extract payment terms
        extracted['payment_terms'] = self._extract_payment_terms(text)

        # Extract billing and shipping blocks
        bill_to, ship_to, buyer = self._extract_party_blocks(text)
        extracted['bill_to'] = bill_to
        extracted['ship_to'] = ship_to
        extracted['buyer'] = buyer

        # Extract tax IDs
        tax_ids = self._extract_tax_ids(text)
        extracted.update(tax_ids)

        # Extract supplier contact details
        supplier_details = self._extract_supplier_details(text)
        extracted.update(supplier_details)

        # Extract bank details
        bank = self._extract_bank_details(text)
        extracted.update(bank)

        # Extract discounts and charges
        charges = self._extract_discounts_and_charges(text)
        extracted.update(charges)

        # Extract overall tax rate if present
        extracted['tax_rate'] = extracted.get('tax_rate') or self._extract_tax_rate(text)

        # Additional label-value pairs
        additional_fields = self._extract_additional_fields(text)
        extracted['additional_fields'] = additional_fields

        # Attach raw text for downstream use
        extracted['raw_text'] = text
        
        return extracted
    
    def _extract_supplier(self, text: str, words: List[Dict[str, Any]]) -> Optional[str]:
        """Extract supplier name (usually at the top of the document)"""
        
        # Prefer bounding boxes when available
        if words:
            # Sort words by Y coordinate (top to bottom)
            sorted_words = sorted(words, key=lambda w: w['bbox']['y'])
            
            # Take words from the top 20% of the document
            top_20_percent = int(len(sorted_words) * 0.2)
            top_words = sorted_words[:max(top_20_percent, 5)]
            
            # Group words by lines (similar Y coordinates)
            lines = {}
            for word in top_words:
                y = word['bbox']['y']
                line_key = y // 15  # Group words within 15 pixels
                
                if line_key not in lines:
                    lines[line_key] = []
                lines[line_key].append(word)
            
            # Find the line with the most confident, substantial text
            best_line = None
            best_score = 0
            
            for line_words in lines.values():
                # Sort words in line by X coordinate
                line_words.sort(key=lambda w: w['bbox']['x'])
                line_text = ' '.join(w['text'] for w in line_words if w['text'].strip())
                
                # Score based on length and confidence
                if len(line_text) > 5:  # Minimum length
                    avg_confidence = sum(w['confidence'] for w in line_words) / len(line_words)
                    score = len(line_text) * avg_confidence
                    
                    if score > best_score:
                        best_score = score
                        best_line = line_text
            
            if best_line and len(best_line) > 3:
                return best_line
        
        # Fallback: use the first substantive line from text
        if text:
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            header_lines = lines[:15]  # examine top part
            blacklist = ['invoice', 'bill to', 'billed to', 'ship to', 'date', 'due', 'total', 'amount', 'tax', 'subtotal']
            for l in header_lines:
                low = l.lower()
                if any(b in low for b in blacklist):
                    continue
                # Prefer lines that look like company names
                if any(tag in l for tag in ['Inc', 'INC', 'LLC', 'Ltd', 'Co.', 'Company']):
                    return l
                # Or lines with multiple words and capital letters
                if sum(1 for c in l if c.isupper()) >= 3 and len(l.split()) >= 2:
                    return l
            # As last resort, return the first non-blacklisted line
            for l in header_lines:
                low = l.lower()
                if not any(b in low for b in blacklist):
                    return l
        
        return None
        
        # Sort words by Y coordinate (top to bottom)
        sorted_words = sorted(words, key=lambda w: w['bbox']['y'])
        
        # Take words from the top 20% of the document
        top_20_percent = int(len(sorted_words) * 0.2)
        top_words = sorted_words[:max(top_20_percent, 5)]
        
        # Group words by lines (similar Y coordinates)
        lines = {}
        for word in top_words:
            y = word['bbox']['y']
            line_key = y // 15  # Group words within 15 pixels
            
            if line_key not in lines:
                lines[line_key] = []
            lines[line_key].append(word)
        
        # Find the line with the most confident, substantial text
        best_line = None
        best_score = 0
        
        for line_words in lines.values():
            # Sort words in line by X coordinate
            line_words.sort(key=lambda w: w['bbox']['x'])
            line_text = ' '.join(w['text'] for w in line_words if w['text'].strip())
            
            # Score based on length and confidence
            if len(line_text) > 5:  # Minimum length
                avg_confidence = sum(w['confidence'] for w in line_words) / len(line_words)
                score = len(line_text) * avg_confidence
                
                if score > best_score:
                    best_score = score
                    best_line = line_text
        
        return best_line if best_line and len(best_line) > 3 else None

    def _detect_currency_details(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """Detect currency ISO code and symbol from text."""
        # symbol to ISO map (subset)
        symbol_to_code = {
            '$': 'USD', '€': 'EUR', '£': 'GBP', '¥': 'JPY', '₹': 'INR', '₩': 'KRW', '₽': 'RUB', '₺': 'TRY', '₫': 'VND', '฿': 'THB', '₪': 'ILS', 'R$': 'BRL', 'A$': 'AUD', 'C$': 'CAD', 'HK$': 'HKD', 'S$': 'SGD'
        }
        # Try ISO detection first
        code = self._detect_currency(text)
        symbol_found = None
        if code:
            # Find matching symbol presence
            for sym, sym_code in symbol_to_code.items():
                if sym in text and sym_code == code:
                    symbol_found = sym
                    break
        if not code:
            # Try detect by symbol
            for sym, sym_code in symbol_to_code.items():
                if sym in text:
                    return sym_code, sym
        return code, symbol_found
    
    def _extract_with_patterns(self, text: str, patterns: List[str]) -> Optional[str]:
        """Extract field using regex patterns"""
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Return the last captured group to avoid optional label groups
                group_count = len(match.groups())
                if group_count >= 1:
                    return match.group(group_count).strip()
                return match.group(0).strip()
        
        return None
    
    def _extract_line_items(self, words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract line items from table structure"""
        
        if len(words) < 10:
            return []
        
        # Try to detect header row by keywords to infer columns
        header_keywords = {
            'description': ['description', 'item', 'product', 'service'],
            'quantity': ['qty', 'quantity', 'qnty'],
            'unit_price': ['unit price', 'price', 'rate'],
            'amount': ['amount', 'total', 'line total'],
            'tax_rate': ['tax %', 'tax rate', 'vat %'],
            'item_code': ['sku', 'code', 'hsn', 'item code']
        }
        columns = {}
        # Build quick index by lines
        rows = {}
        for word in words:
            y = word['bbox']['y']
            row_key = y // 20
            
            if row_key not in rows:
                rows[row_key] = []
            rows[row_key].append(word)
        
        # Sort rows by Y coordinate
        sorted_rows = sorted(rows.items())

        # Identify possible header row (first with multiple keywords)
        for row_key, row_words in sorted_rows[:10]:
            text_line = ' '.join(w['text'].lower() for w in row_words)
            hits = 0
            # estimate x positions of each header keyword
            for col, keys in header_keywords.items():
                for k in keys:
                    if k in text_line:
                        # find the x of the matched word
                        for w in row_words:
                            if k in w['text'].lower():
                                columns[col] = w['bbox']['x']
                                hits += 1
                                break
                        break
            if hits >= 2:
                break
        
        line_items = []
        
        for row_key, row_words in sorted_rows:
            # Sort words in row by X coordinate
            row_words.sort(key=lambda w: w['bbox']['x'])
            
            # Look for numeric patterns that might be quantities, prices, amounts
            row_text = ' '.join(w['text'] for w in row_words)
            
            # Skip header rows or rows without numbers
            if not re.search(r'\d+\.?\d*', row_text):
                continue
            
            # Extract potential line item data
            numbers = re.findall(r'\d+\.?\d*', row_text)
            text_parts = re.split(r'\d+\.?\d*', row_text)
            
            if len(numbers) >= 2:  # At least quantity and amount
                description = text_parts[0].strip() if text_parts else ""
                
                # Try to identify quantity, unit_price, amount
                if len(numbers) >= 3:
                    quantity = self._parse_number(numbers[0])
                    unit_price = self._parse_number(numbers[1])
                    amount = self._parse_number(numbers[2])
                elif len(numbers) == 2:
                    quantity = self._parse_number(numbers[0])
                    unit_price = None
                    amount = self._parse_number(numbers[1])
                else:
                    continue
                
                # Calculate confidence based on word confidences in this row
                avg_confidence = sum(w['confidence'] for w in row_words) / len(row_words)
                
                # Attempt to capture item_code and tax_rate from positional columns
                item_code = None
                tax_rate = None
                # If columns were detected, pick nearest word to that x
                def nearest_text(target_x: int) -> Optional[str]:
                    if not row_words:
                        return None
                    closest = min(row_words, key=lambda w: abs(w['bbox']['x'] - target_x))
                    return closest['text'] if closest else None

                if 'item_code' in columns:
                    item_code = nearest_text(columns['item_code'])
                    # avoid picking numeric amounts mistakenly
                    if item_code and re.search(r"^\d+\.?\d*$", item_code):
                        item_code = None
                if 'tax_rate' in columns:
                    tr = nearest_text(columns['tax_rate'])
                    if tr:
                        m = re.search(r"(\d{1,3}\.?\d*)\s*%", tr)
                        if m:
                            tax_rate = self._parse_number(m.group(1))
                
                line_item = {
                    'description': description if len(description) > 2 else None,
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'amount': amount,
                    'confidence': avg_confidence,
                    'item_code': item_code,
                    'tax_rate': tax_rate
                }
                
                line_items.append(line_item)
        
        return line_items[:10]  # Limit to 10 items for prototype
    
    def _parse_number(self, text: str) -> Optional[float]:
        """Parse number from text, stripping currency symbols and whitespace"""
        try:
            s = str(text)
            # Remove common currency symbols and thousands separators
            s = s.replace(',', '')
            for sym in ['$', '€', '£', '¥', '₹', '₩', '₽', '₺', '₫', '฿', '₦', '₪', 'R$', 'A$', 'C$', 'HK$', 'S$', '₴']:
                s = s.replace(sym, '')
            # Keep digits, dot, and minus only
            cleaned = re.sub(r"[^0-9\.-]", '', s).strip()
            if cleaned in ['', '-', '.', '--']:
                return None
            return float(cleaned)
        except (ValueError, TypeError):
            return None
    
    def _detect_currency(self, text: str) -> Optional[str]:
        """Detect currency from text and return ISO code. Also set symbol in extracted data later."""
        # Map symbols and common labels to ISO codes
        symbol_map = {
            '$': 'USD', 'US$': 'USD', 'U.S. Dollars': 'USD',
            '€': 'EUR',
            '£': 'GBP',
            '¥': 'JPY', '円': 'JPY',
            '₹': 'INR', 'Rs': 'INR', 'Rs.': 'INR',
            'C$': 'CAD', 'CAD': 'CAD',
            'A$': 'AUD', 'AUD': 'AUD',
            'NZ$': 'NZD', 'NZD': 'NZD',
            'HK$': 'HKD', 'HKD': 'HKD',
            'S$': 'SGD', 'SGD': 'SGD',
            'CHF': 'CHF',
            '₩': 'KRW', 'KRW': 'KRW',
            '₽': 'RUB', 'RUB': 'RUB',
            'R$': 'BRL', 'BRL': 'BRL',
            'MX$': 'MXN', 'MXN': 'MXN',
            '₺': 'TRY', 'TRY': 'TRY',
            '₫': 'VND', 'VND': 'VND',
            '฿': 'THB', 'THB': 'THB',
            '₴': 'UAH', 'UAH': 'UAH',
            'ZAR': 'ZAR',
            'SEK': 'SEK', 'NOK': 'NOK', 'DKK': 'DKK', 'PLN': 'PLN', 'CZK': 'CZK', 'HUF': 'HUF',
            'AED': 'AED', 'SAR': 'SAR', 'QAR': 'QAR', 'BHD': 'BHD', 'OMR': 'OMR', 'KWD': 'KWD',
            'ILS': 'ILS', '₪': 'ILS',
            'MYR': 'MYR', 'IDR': 'IDR', 'PHP': 'PHP',
            'EGP': 'EGP', 'NGN': 'NGN', 'KES': 'KES', 'GHS': 'GHS', 'TZS': 'TZS', 'UGX': 'UGX'
        }

        # Check for ISO codes directly
        for code in set(symbol_map.values()).union({'USD','EUR','GBP','JPY','INR','CAD','AUD','NZD','HKD','SGD','CHF','KRW','RUB','BRL','MXN','TRY','VND','THB','UAH','ZAR','SEK','NOK','DKK','PLN','CZK','HUF','AED','SAR','QAR','BHD','OMR','KWD','ILS','MYR','IDR','PHP','EGP','NGN','KES','GHS','TZS','UGX'}):
            if re.search(fr"\b{code}\b", text, re.IGNORECASE):
                return code.upper()

        # Check for symbols/labels near amounts
        for sym, code in symbol_map.items():
            if sym in text:
                return code

        # As fallback, infer by common currency words
        if re.search(r'\b(dollars|usd)\b', text, re.IGNORECASE):
            return 'USD'
        if re.search(r'\b(eur|euro|euros)\b', text, re.IGNORECASE):
            return 'EUR'
        if re.search(r'\b(pounds|gbp)\b', text, re.IGNORECASE):
            return 'GBP'
        # Default to None to avoid wrong assumptions; processor can set later
        return None

    def _extract_po_number(self, text: str) -> Optional[str]:
        patterns = [
            r'purchase\s*order\s*(no\.|number|#)?\s*:?\s*([A-Z0-9\-/]+)',
            r'\bPO\s*(no\.|number|#)?\s*:?\s*([A-Z0-9\-/]+)'
        ]
        return self._extract_with_patterns(text, patterns)

    def _extract_payment_terms(self, text: str) -> Optional[str]:
        patterns = [
            r'payment\s*terms\s*:?\s*([^\n]+)',
            r'\bNet\s*(\d{1,3})\b',
            r'due\s*in\s*(\d{1,3})\s*days'
        ]
        val = self._extract_with_patterns(text, patterns)
        return val

    def _extract_party_blocks(self, text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Extract bill to / ship to blocks and buyer name if present."""
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        bill_to = None
        ship_to = None
        buyer = None
        def extract_block(start_idx: int) -> str:
            blk = []
            for j in range(start_idx+1, min(start_idx+6, len(lines))):
                low = lines[j].lower()
                if re.search(r'^(invoice|date|due|total|amount|tax|subtotal|payment|po\b|gst|vat)', low):
                    break
                blk.append(lines[j])
            return '\n'.join(blk).strip() if blk else None
        for i, l in enumerate(lines):
            low = l.lower()
            if bill_to is None and re.search(r'\b(bill\s*to|billed\s*to|sold\s*to|invoice\s*to)\b', low):
                bill_to = extract_block(i)
            if ship_to is None and re.search(r'\b(ship\s*to|deliver\s*to)\b', low):
                ship_to = extract_block(i)
            if buyer is None and re.search(r'\b(customer|buyer|client)\b', low):
                buyer = extract_block(i) or lines[i]
        return bill_to, ship_to, buyer

    def _extract_tax_ids(self, text: str) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {
            'gstin': None,
            'vat_id': None,
            'pan': None,
        }
        m = re.search(r'\bGSTIN\b\s*:?\s*([0-9A-Z]{15})', text, re.IGNORECASE)
        if m:
            out['gstin'] = m.group(1)
        m = re.search(r'\bVAT\b\s*(ID|No\.|Number)?\s*:?\s*([A-Z0-9\-]+)', text, re.IGNORECASE)
        if m:
            out['vat_id'] = m.group(len(m.groups()))
        m = re.search(r'\bPAN\b\s*:?\s*([A-Z]{5}\d{4}[A-Z])', text, re.IGNORECASE)
        if m:
            out['pan'] = m.group(1)
        return out

    def _extract_supplier_details(self, text: str) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {
            'supplier_address': None,
            'supplier_email': None,
            'supplier_phone': None,
            'supplier_tax_id': None
        }
        # Email
        m = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text)
        if m:
            out['supplier_email'] = m.group(0)
        # Phone (generic)
        m = re.search(r'(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)?\d{3,5}[\s-]?\d{3,5}', text)
        if m:
            out['supplier_phone'] = m.group(0)
        # Address: heuristic near supplier name (first lines)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for i, l in enumerate(lines[:20]):
            if re.search(r'\b(address|addr\.)\b', l.lower()):
                blk = []
                for j in range(i+1, min(i+5, len(lines))):
                    if re.search(r'^(invoice|date|due|total|tax|gst|vat|po\b)', lines[j].lower()):
                        break
                    blk.append(lines[j])
                if blk:
                    out['supplier_address'] = '\n'.join(blk)
                    break
        # Tax id generic
        m = re.search(r'(tax\s*id|tin)\s*:?\s*([A-Z0-9\-]+)', text, re.IGNORECASE)
        if m:
            out['supplier_tax_id'] = m.group(len(m.groups()))
        return out

    def _extract_bank_details(self, text: str) -> Dict[str, Optional[str]]:
        out: Dict[str, Optional[str]] = {
            'bank_account': None,
            'ifsc': None,
            'iban': None,
            'swift': None
        }
        m = re.search(r'\bAccount\s*(No\.|Number)?\s*:?\s*([A-Z0-9\-]+)', text, re.IGNORECASE)
        if m:
            out['bank_account'] = m.group(len(m.groups()))
        m = re.search(r'\bIFSC\b\s*:?\s*([A-Z]{4}0[A-Z0-9]{6})', text)
        if m:
            out['ifsc'] = m.group(1)
        m = re.search(r'\bIBAN\b\s*:?\s*([A-Z0-9]{15,34})', text)
        if m:
            out['iban'] = m.group(1)
        m = re.search(r'\bSWIFT\b\s*:?\s*([A-Z0-9]{8,11})', text)
        if m:
            out['swift'] = m.group(1)
        return out

    def _extract_discounts_and_charges(self, text: str) -> Dict[str, Optional[float]]:
        out: Dict[str, Optional[float]] = {
            'discount': None,
            'shipping': None,
            'handling': None,
            'other_charges': None
        }
        def num(pats: List[str]) -> Optional[float]:
            for p in pats:
                m = re.search(p, text, re.IGNORECASE)
                if m:
                    return self._parse_number(m.group(len(m.groups()))) if m.groups() else self._parse_number(m.group(0))
            return None
        out['discount'] = num([r'discount\s*:?\s*\$?\s*([0-9,]+\.?\d*)'])
        out['shipping'] = num([r'(shipping|delivery|freight)\s*:?\s*\$?\s*([0-9,]+\.?\d*)'])
        out['handling'] = num([r'handling\s*:?\s*\$?\s*([0-9,]+\.?\d*)'])
        out['other_charges'] = num([r'(other\s*charges|misc\.|surcharges?)\s*:?\s*\$?\s*([0-9,]+\.?\d*)'])
        return out

    def _extract_tax_rate(self, text: str) -> Optional[float]:
        m = re.search(r'(tax|vat)[^\n%]*?(\d{1,3}\.?\d*)\s*%', text, re.IGNORECASE)
        if m:
            return self._parse_number(m.group(2))
        return None

    def _extract_additional_fields(self, text: str) -> Dict[str, Any]:
        """Generic label:value extraction to capture extra fields."""
        fields: Dict[str, Any] = {}
        for line in [l.strip() for l in text.splitlines() if l.strip()]:
            m = re.match(r'([A-Za-z][A-Za-z\s\-/&]+?)\s*[:\-]\s*(.+)$', line)
            if m:
                label = m.group(1).strip().lower()
                value = m.group(2).strip()
                # Skip common labels already captured
                if any(k in label for k in ['total','subtotal','tax','amount','date','invoice','bill to','ship to','payment terms','po','gst','vat','pan','account','iban','swift','ifsc']):
                    continue
                # Avoid lines that are just numeric totals
                fields[label] = value
        return fields
    
    async def _extract_with_layoutlm(self, ocr_result: Dict[str, Any], doc_type: DocumentType) -> Dict[str, Any]:
        """Extract fields using LayoutLMv3 and merge with rule-based fallback."""
        try:
            if self._layoutlm is None:
                self._layoutlm = LayoutLMEngine(
                    model_name=LAYOUTLM_MODEL,
                    device_pref=LAYOUTLM_DEVICE,
                    confidence_threshold=float(LAYOUTLM_CONFIDENCE_THRESHOLD),
                )

            image_paths: List[str] = ocr_result.get('image_paths', [])
            page_results = ocr_result.get('page_results', [])
            page_texts = [p.get('text', '') for p in page_results]

            if not image_paths:
                logger.info("No image paths available for LayoutLM; falling back to rules")
                return self._extract_with_rules(ocr_result, doc_type)

            entity_pages = self._layoutlm.predict_entities(image_paths)
            hints = LayoutLMEngine.map_entities_to_fields(entity_pages, page_texts)

            # Start with rule-based results, then enrich with LayoutLM hints
            base = self._extract_with_rules(ocr_result, doc_type)

            # If LayoutLM provided direct fields (future richer mapping), prefer them; for now, merge hints
            for k, v in hints.items():
                # Only set if base doesn't have the field or it's empty
                if k.endswith('_hint'):
                    base.setdefault('additional_fields', {})
                    base['additional_fields'][k] = v
                else:
                    if not base.get(k):
                        base[k] = v

            # Attach a simple debug block with entities per page
            base.setdefault('additional_fields', {})
            base['additional_fields']['layoutlm_entities'] = entity_pages

            # Visible markers to confirm LayoutLM participation
            total_entities = sum(len(p.get('entities', [])) for p in entity_pages)
            base['additional_fields']['layoutlm_enabled'] = True
            base['additional_fields']['layoutlm_model'] = LAYOUTLM_MODEL
            base['additional_fields']['layoutlm_device'] = getattr(self._layoutlm, 'device', LAYOUTLM_DEVICE)
            base['additional_fields']['layoutlm_entity_count'] = total_entities

            logger.info(
                f"LayoutLM enabled: {total_entities} entities across {len(entity_pages)} pages on device '{getattr(self._layoutlm, 'device', LAYOUTLM_DEVICE)}'"
            )

            return base
        except Exception as e:
            logger.warning(f"LayoutLM extraction failed, using fallback: {e}")
            return self._extract_with_rules(ocr_result, doc_type)