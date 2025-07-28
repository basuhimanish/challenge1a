import fitz  # PyMuPDF
import os
import json
from collections import defaultdict
import logging
from pathlib import Path
import unicodedata
import re

# Language detection (install with: pip install langdetect)
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0  # For consistent results
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    logging.warning("langdetect not available. Language detection disabled.")

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

class MultilingualPDFExtractor:
    def __init__(self):
        # Language-specific patterns for better text cleaning
        self.language_patterns = {
            'arabic': re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+'),
            'chinese': re.compile(r'[\u4e00-\u9fff]+'),
            'japanese': re.compile(r'[\u3040-\u309F\u30A0-\u30FF\u4e00-\u9fff]+'),
            'korean': re.compile(r'[\uAC00-\uD7AF\u1100-\u11FF\u3130-\u318F]+'),
            'cyrillic': re.compile(r'[\u0400-\u04FF]+'),
            'devanagari': re.compile(r'[\u0900-\u097F]+'),
            'latin': re.compile(r'[A-Za-z\u00C0-\u017F\u0100-\u024F]+')
        }
        
        # RTL languages
        self.rtl_languages = {'ar', 'he', 'fa', 'ur'}
        
    def detect_language(self, text):
        """Detect the language of the text"""
        if not LANGDETECT_AVAILABLE:
            return 'unknown'
        
        try:
            # Clean text for better detection
            clean_text = self.clean_text_for_detection(text)
            if len(clean_text.strip()) < 10:
                return 'unknown'
            return detect(clean_text)
        except:
            return 'unknown'
    
    def clean_text_for_detection(self, text):
        """Clean text for language detection"""
        if not text:
            return ""
        
        # Remove excessive whitespace and special characters
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'[^\w\s\u0080-\uFFFF]', ' ', text)
        return text.strip()
    
    def normalize_text(self, text, language='unknown'):
        """Normalize text based on language"""
        if not text:
            return ""
        
        # Unicode normalization
        text = unicodedata.normalize('NFKC', text)
        
        # Language-specific normalization
        if language in self.rtl_languages:
            # For RTL languages, preserve text direction
            text = text.strip()
        else:
            # For LTR languages, standard cleaning
            text = re.sub(r'\s+', ' ', text).strip()
        
        return text
    
    def is_likely_heading(self, text, language='unknown'):
        """Determine if text is likely a heading based on content"""
        if len(text) > 200:  # Too long for a heading
            return False
        
        # Language-specific heading patterns
        if language in ['zh', 'ja']:  # Chinese/Japanese
            # Check for chapter markers
            if re.search(r'[第章节]\s*[一二三四五六七八九十\d]+', text):
                return True
        elif language in ['ar', 'he']:  # Arabic/Hebrew
            # Check for common heading patterns
            if re.search(r'^[\u0600-\u06FF\s]*[\d\u0660-\u0669]+[\u0600-\u06FF\s]*$', text):
                return True
        
        # General patterns
        if re.search(r'^\d+[\.\)]\s', text):  # Numbered headings
            return True
        if text.isupper() and len(text) < 50:  # Short uppercase text
            return True
        if re.search(r'^(Chapter|Section|Part)\s+\d+', text, re.IGNORECASE):
            return True
        
        return False
    
    def extract_title_and_headings(self, pdf_path):
        """Extract title and headings with multilingual support"""
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            logging.error(f"Failed to open PDF {pdf_path}: {e}")
            return None
        
        font_sizes = defaultdict(int)
        text_blocks = []
        all_text = ""  # For language detection
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            blocks = page.get_text("dict")["blocks"]
            
            for block in blocks:
                if "lines" not in block:
                    continue
                    
                for line in block["lines"]:
                    line_text = ""
                    line_font_size = 0
                    
                    for span in line["spans"]:
                        font_size = round(span["size"], 1)
                        font_sizes[font_size] += 1
                        span_text = span["text"]
                        
                        # Normalize text
                        normalized_span = self.normalize_text(span_text)
                        line_text += normalized_span
                        line_font_size = font_size  # Use last span's font size
                    
                    if line_text.strip():
                        text_blocks.append({
                            "text": line_text.strip(),
                            "font_size": line_font_size,
                            "page": page_num + 1
                        })
                        all_text += " " + line_text.strip()
        
        total_pages = len(doc)
        doc.close()
        
        # Detect document language
        document_language = self.detect_language(all_text)
        logging.info(f"Detected language: {document_language}")
        
        # Analyze font sizes for hierarchy
        sorted_fonts = sorted(font_sizes.items(), key=lambda x: (-x[1], -x[0]))  # Sort by frequency, then size
        
        # Create font mapping based on frequency and size
        font_mapping = {}
        unique_sizes = sorted(set(font_sizes.keys()), reverse=True)
        
        if len(unique_sizes) >= 1:
            font_mapping["title"] = unique_sizes[0]
        if len(unique_sizes) >= 2:
            font_mapping["H1"] = unique_sizes[1]
        if len(unique_sizes) >= 3:
            font_mapping["H2"] = unique_sizes[2]
        if len(unique_sizes) >= 4:
            font_mapping["H3"] = unique_sizes[3]
        
        # Extract title and outline
        title = ""
        outline = []
        
        for block in text_blocks:
            size = round(block["font_size"], 1)
            text = block["text"]
            page = block["page"]
            
            # Enhanced title detection
            if size == font_mapping.get("title") and not title:
                if page <= 2 and len(text) < 150:  # Title usually on first pages and not too long
                    title = text
            elif size == font_mapping.get("H1"):
                if self.is_likely_heading(text, document_language) or len(text) < 100:
                    outline.append({"level": "H1", "text": text, "page": page})
            elif size == font_mapping.get("H2"):
                if self.is_likely_heading(text, document_language) or len(text) < 100:
                    outline.append({"level": "H2", "text": text, "page": page})
            elif size == font_mapping.get("H3"):
                if self.is_likely_heading(text, document_language) or len(text) < 100:
                    outline.append({"level": "H3", "text": text, "page": page})
        
        # If no title found using font size, try to find it from first page
        if not title and text_blocks:
            first_page_blocks = [b for b in text_blocks if b["page"] == 1]
            if first_page_blocks:
                # Look for the largest font on first page
                max_font_size = max(b["font_size"] for b in first_page_blocks)
                title_candidates = [b for b in first_page_blocks if b["font_size"] == max_font_size]
                if title_candidates and len(title_candidates[0]["text"]) < 150:
                    title = title_candidates[0]["text"]
        
        return {
            "title": title,
            "outline": outline,
            "language": document_language,
            "font_analysis": {
                "detected_fonts": dict(sorted_fonts[:10]),  # Top 10 fonts by frequency
                "font_mapping": font_mapping
            },
            "statistics": {
                "total_pages": total_pages,
                "total_headings": len(outline),
                "headings_by_level": {
                    level: len([h for h in outline if h["level"] == level])
                    for level in ["H1", "H2", "H3"]
                }
            }
        }

def main():
    input_dir = "/app/input"
    output_dir = "/app/output"
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Initialize extractor
    extractor = MultilingualPDFExtractor()
    
    # Process all PDF files
    pdf_files = [f for f in os.listdir(input_dir) if f.endswith(".pdf")]
    
    if not pdf_files:
        logging.warning(f"No PDF files found in {input_dir}")
        return
    
    logging.info(f"Found {len(pdf_files)} PDF files to process")
    
    results_summary = []
    
    for filename in pdf_files:
        pdf_path = os.path.join(input_dir, filename)
        logging.info(f"Processing {pdf_path}")
        
        result = extractor.extract_title_and_headings(pdf_path)
        
        if result is None:
            logging.warning(f"Skipping {pdf_path} due to previous errors.")
            continue
        
        # Save individual result
        output_filename = filename.replace(".pdf", ".json")
        output_path = os.path.join(output_dir, output_filename)
        
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)  # ensure_ascii=False for proper Unicode
            logging.info(f"Wrote output to {output_path}")
            
            # Add to summary
            results_summary.append({
                "filename": filename,
                "title": result.get("title", ""),
                "language": result.get("language", "unknown"),
                "headings_count": len(result.get("outline", [])),
                "pages": result.get("statistics", {}).get("total_pages", 0)
            })
            
        except Exception as e:
            logging.error(f"Failed to write JSON for {pdf_path}: {e}")
    
    # Save processing summary
    summary_path = os.path.join(output_dir, "processing_summary.json")
    try:
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump({
                "processed_files": len(results_summary),
                "files": results_summary,
                "languages_detected": list(set(r["language"] for r in results_summary))
            }, f, indent=2, ensure_ascii=False)
        logging.info(f"Processing summary saved to {summary_path}")
    except Exception as e:
        logging.error(f"Failed to write processing summary: {e}")

if __name__ == "__main__":
    logging.info("Starting multilingual PDF processing")
    main()
    logging.info("Completed multilingual PDF processing")