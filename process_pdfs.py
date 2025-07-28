import fitz  # PyMuPDF
import os
import json
import unicodedata
from collections import defaultdict
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

def is_bold(span):
    return (span.get("flags", 0) & 2 != 0) or ("Bold" in span.get("font", ""))

def extract_title_and_headings(pdf_path):
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logging.error(f"Failed to open PDF {pdf_path}: {e}")
        return None

    font_stats = defaultdict(int)
    text_blocks = []

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if "lines" not in block:
                continue
            for line in block["lines"]:
                line_text = ""
                y = 0
                font_size = 0
                bold = False
                fonts = set()
                for span in line["spans"]:
                    font_size = round(span["size"], 1)
                    y = span["bbox"][1]
                    fonts.add(span.get("font", ""))
                    if is_bold(span):
                        bold = True
                    line_text += span["text"] + " "  # Preserve spacing
                if line_text.strip():
                    font_key = (font_size, bold)
                    font_stats[font_key] += 1
                    text_blocks.append({
                        "text": line_text.strip(),
                        "font_size": font_size,
                        "font_names": list(fonts),
                        "bold": bold,
                        "y": y,
                        "page": page_num + 1
                    })

    sorted_fonts = sorted(font_stats.items(), key=lambda x: (-x[0][0], -x[1]))
    font_mapping = {}
    if sorted_fonts:
        font_mapping["title"] = sorted_fonts[0][0]
        if len(sorted_fonts) > 1:
            font_mapping["H1"] = sorted_fonts[1][0]
        if len(sorted_fonts) > 2:
            font_mapping["H2"] = sorted_fonts[2][0]
        if len(sorted_fonts) > 3:
            font_mapping["H3"] = sorted_fonts[3][0]
        if len(sorted_fonts) > 4:
            font_mapping["H4"] = sorted_fonts[4][0]
    else:
        logging.warning(f"PDF {pdf_path} may not have enough font variety for heading detection.")

    def group_blocks(blocks):
        grouped = []
        current_group = []
        prev_size = None
        prev_bold = None
        prev_page = None
        for block in blocks:
            size = block["font_size"]
            bold = block["bold"]
            page = block["page"]
            if size == prev_size and bold == prev_bold and page == prev_page:
                current_group.append(block)
            else:
                if current_group:
                    grouped.append(current_group)
                current_group = [block]
            prev_size = size
            prev_bold = bold
            prev_page = page
        if current_group:
            grouped.append(current_group)
        return grouped

    grouped_blocks = group_blocks(text_blocks)

    title = ""
    outline = []
    heading_freq = {}
    headings_on_page = defaultdict(int)

    unwanted_keywords = set()  # Disabled for multilingual support

    for group in grouped_blocks:
        if not group:
            continue
        size = group[0]["font_size"]
        bold = group[0]["bold"]
        font_key = (size, bold)
        page = group[0]["page"]
        level = None
        for k, v in font_mapping.items():
            if font_key == v:
                level = k
                break

        combined_text = " ".join([b["text"] for b in group])
        key = unicodedata.normalize("NFKC", combined_text.strip().lower())
        word_count = len(combined_text.split())

        # --- Filter title ---
        if level == "title" and not title and page <= 1 and word_count < 20:
            if any(x in key for x in unwanted_keywords) or "---" in key:
                continue
            title = combined_text.strip()
            continue

        # --- Filter headers ---
        if level and level != "title":
            if word_count > 20:
                continue
            if combined_text.endswith(".") or "@" in key:
                continue
            if combined_text.count(":") > 2:
                continue
            if any(word in key for word in unwanted_keywords):
                continue
            heading_freq[key] = heading_freq.get(key, 0) + 1
            if heading_freq[key] > 1:
                continue
            if headings_on_page[page] >= 5:
                continue  # limit per page

            cleaned_text = combined_text.strip()
            outline.append({
                "level": level,
                "text": cleaned_text,
                "page": page
            })
            headings_on_page[page] += 1

    # Fallback: if title still empty, take first line on page 1
    if not title:
        for block in text_blocks:
            if block["page"] == 1:
                title = block["text"]
                break

    return {
        "title": title,
        "outline": outline
    }

def main():
    input_dir = "/app/input"
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)

    for filename in os.listdir(input_dir):
        if filename.endswith(".pdf"):
            pdf_path = os.path.join(input_dir, filename)
            logging.info(f"Processing {pdf_path}")
            result = extract_title_and_headings(pdf_path)
            if result is None:
                logging.warning(f"Skipping {pdf_path} due to previous errors.")
                continue
            output_filename = filename.replace(".pdf", ".json")
            output_path = os.path.join(output_dir, output_filename)
            try:
                with open(output_path, "w", encoding="utf-8") as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                logging.info(f"Wrote output to {output_path}")
            except Exception as e:
                logging.error(f"Failed to write JSON for {pdf_path}: {e}")

if __name__ == "__main__":
    logging.info("Starting processing pdfs")
    main()
    logging.info("Completed processing pdfs")