"""
OCR Processor using Tesseract with OpenCV preprocessing
"""

import cv2
import numpy as np
import pytesseract
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional
from PIL import Image
import pdf2image
from pypdf import PdfReader

from .config import TEMP_DIR, TESSERACT_LANGS, PSM_DEFAULT, OEM_DEFAULT, PDF_DPI

logger = logging.getLogger(__name__)


class OCRProcessor:
    """Handles OCR processing with preprocessing"""
    
    def __init__(self):
        # Configure tesseract if needed
        # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Uncomment if needed
        pass
    
    async def process(self, file_path: Path, job_id: str) -> Optional[Dict[str, Any]]:
        """Process document through OCR pipeline"""
        
        try:
            # Create job temp directory
            job_temp_dir = TEMP_DIR / job_id
            job_temp_dir.mkdir(exist_ok=True)
            
            # If PDF, first try to extract text directly (born-digital PDFs)
            if file_path.suffix.lower() == '.pdf':
                pdf_text_pages = self._extract_text_from_pdf(file_path)
                if pdf_text_pages:
                    # Also convert to images for downstream models (LayoutLM)
                    image_paths = self._convert_to_images(file_path, job_temp_dir)

                    # Build combined result from extracted text
                    combined_text = []
                    for i, page_text in enumerate(pdf_text_pages, start=1):
                        combined_text.append(f"--- Page {i} ---")
                        combined_text.append(page_text.strip())
                        combined_text.append("")

                    result = {
                        'pages': len(pdf_text_pages),
                        'full_text': '\n'.join(combined_text),
                        'all_words': [],  # No bounding boxes in text extraction
                        'total_words': 0,
                        'page_results': [
                            {'page': i, 'text': page_text.strip(), 'words': [], 'word_count': 0}
                            for i, page_text in enumerate(pdf_text_pages, start=1)
                        ],
                        'image_paths': [str(p) for p in image_paths]
                    }

                    # Save OCR-like result
                    import json
                    ocr_file = job_temp_dir / "ocr_result.json"
                    with open(ocr_file, "w") as f:
                        json.dump(result, f, indent=2)

                    logger.info(f"PDF text extracted without OCR for job {job_id}")
                    return result

            # Convert to images if not handled above
            images = self._convert_to_images(file_path, job_temp_dir)
            
            # Process each page
            ocr_results = []
            for i, image_path in enumerate(images):
                logger.info(f"Processing page {i+1}/{len(images)} for job {job_id}")
                
                # Preprocess image
                processed_image = self._preprocess_image(image_path)
                
                # Perform OCR
                page_result = self._perform_ocr(processed_image, i+1)
                if page_result:
                    ocr_results.append(page_result)
            
            if not ocr_results:
                logger.error(f"No OCR results for job {job_id}")
                return None
            
            # Combine results
            combined_result = self._combine_page_results(ocr_results)
            combined_result['image_paths'] = [str(p) for p in images]
            
            # Save OCR result
            import json
            ocr_file = job_temp_dir / "ocr_result.json"
            with open(ocr_file, "w") as f:
                json.dump(combined_result, f, indent=2)
            
            logger.info(f"OCR completed for job {job_id}")
            return combined_result
            
        except Exception as e:
            logger.error(f"OCR processing failed for job {job_id}: {str(e)}")
            return None

    def _extract_text_from_pdf(self, file_path: Path) -> List[str]:
        """Extract text from a born-digital PDF using pypdf. Returns list of page texts."""
        try:
            reader = PdfReader(str(file_path))
            page_texts: List[str] = []
            for page in reader.pages:
                txt = page.extract_text() or ""
                page_texts.append(txt)
            
            # Return if any page contains text
            if any(len(t.strip()) > 0 for t in page_texts):
                return page_texts
            return []
        except Exception as e:
            logger.info(f"Direct PDF text extraction failed: {str(e)}. Will fallback to OCR.")
            return []
    
    def _convert_to_images(self, file_path: Path, temp_dir: Path) -> List[Path]:
        """Convert document to images"""
        
        file_ext = file_path.suffix.lower()
        
        if file_ext == '.pdf':
            # Convert PDF to images
            try:
                pages = pdf2image.convert_from_path(
                    file_path, 
                    dpi=PDF_DPI,
                    output_folder=temp_dir,
                    fmt='png'
                )
                
                image_paths = []
                for i, page in enumerate(pages):
                    image_path = temp_dir / f"page_{i+1}.png"
                    page.save(image_path)
                    image_paths.append(image_path)
                
                return image_paths
                
            except Exception as e:
                logger.error(f"PDF conversion failed: {str(e)}")
                return []
        elif file_ext == '.txt':
            # Handle text files by creating a simple image with the text
            try:
                from PIL import Image, ImageDraw, ImageFont
                
                # Read text content
                with open(file_path, 'r', encoding='utf-8') as f:
                    text_content = f.read()
                
                # Create a simple image with the text
                img_width, img_height = 800, 1000
                image = Image.new('RGB', (img_width, img_height), color='white')
                draw = ImageDraw.Draw(image)
                
                try:
                    # Try to use a default font
                    font = ImageFont.load_default()
                except:
                    font = None
                
                # Draw text on image
                lines = text_content.split('\n')
                y_offset = 20
                line_height = 20
                
                for line in lines:
                    if y_offset < img_height - line_height:
                        draw.text((20, y_offset), line, fill='black', font=font)
                        y_offset += line_height
                
                # Save as PNG
                image_path = temp_dir / "text_as_image.png"
                image.save(image_path)
                return [image_path]
                
            except Exception as e:
                logger.error(f"Text file conversion failed: {str(e)}")
                return []
        else:
            # Already an image
            return [file_path]
    
    def _preprocess_image(self, image_path: Path) -> np.ndarray:
        """Preprocess image for better OCR results"""
        
        # Read image
        image = cv2.imread(str(image_path))
        
        if image is None:
            raise ValueError(f"Could not read image: {image_path}")
        
        # Minimal preprocessing for born-digital PDFs: grayscale only
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        return gray
    
    def _deskew_image(self, image: np.ndarray) -> np.ndarray:
        """Correct image rotation/skew"""
        
        try:
            # Find contours
            contours, _ = cv2.findContours(image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            if not contours:
                return image
            
            # Find the largest contour (likely the document)
            largest_contour = max(contours, key=cv2.contourArea)
            
            # Get minimum area rectangle
            rect = cv2.minAreaRect(largest_contour)
            angle = rect[2]
            
            # Correct angle
            if angle < -45:
                angle = 90 + angle
            
            # Only correct if angle is significant
            if abs(angle) > 0.5:
                # Get rotation matrix
                (h, w) = image.shape[:2]
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, angle, 1.0)
                
                # Perform rotation
                rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
                return rotated
            
            return image
            
        except Exception as e:
            logger.warning(f"Deskewing failed: {str(e)}")
            return image
    
    def _perform_ocr(self, image: np.ndarray, page_num: int) -> Optional[Dict[str, Any]]:
        """Perform OCR on preprocessed image"""
        
        try:
            # OCR configuration
            config = f'--oem {OEM_DEFAULT} --psm {PSM_DEFAULT} -l {TESSERACT_LANGS}'
            
            # Get text with bounding boxes
            data = pytesseract.image_to_data(
                image, 
                config=config, 
                output_type=pytesseract.Output.DICT
            )
            
            # Get plain text
            text = pytesseract.image_to_string(image, config=config)
            
            # Process OCR data
            words = []
            for i in range(len(data['text'])):
                if int(data['conf'][i]) > 0:  # Only confident detections
                    word_data = {
                        'text': data['text'][i].strip(),
                        'confidence': float(data['conf'][i]) / 100.0,
                        'bbox': {
                            'x': int(data['left'][i]),
                            'y': int(data['top'][i]),
                            'width': int(data['width'][i]),
                            'height': int(data['height'][i])
                        },
                        'block_num': int(data['block_num'][i]),
                        'par_num': int(data['par_num'][i]),
                        'line_num': int(data['line_num'][i]),
                        'word_num': int(data['word_num'][i])
                    }
                    
                    if word_data['text']:  # Only non-empty text
                        words.append(word_data)
            
            return {
                'page': page_num,
                'text': text.strip(),
                'words': words,
                'word_count': len(words)
            }
            
        except Exception as e:
            logger.error(f"OCR failed for page {page_num}: {str(e)}")
            return None
    
    def _combine_page_results(self, page_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Combine results from multiple pages"""
        
        combined_text = []
        all_words = []
        total_words = 0
        
        for result in page_results:
            combined_text.append(f"--- Page {result['page']} ---")
            combined_text.append(result['text'])
            combined_text.append("")  # Empty line between pages
            
            all_words.extend(result['words'])
            total_words += result['word_count']
        
        return {
            'pages': len(page_results),
            'full_text': '\n'.join(combined_text),
            'all_words': all_words,
            'total_words': total_words,
            'page_results': page_results
        }