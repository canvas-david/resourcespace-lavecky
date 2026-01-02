#!/usr/bin/env python3
"""Extract page images from PDFs for OCR verification pipeline."""

import fitz  # PyMuPDF
from pathlib import Path

SOURCE_DIR = Path("source")
OUTPUT_DIR = Path("images")

def extract_pages():
    """Extract all pages from PDFs as PNG images."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    
    pdfs = sorted(SOURCE_DIR.glob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs to process\n")
    
    total_pages = 0
    
    for pdf_path in pdfs:
        doc = fitz.open(pdf_path)
        doc_name = pdf_path.stem  # e.g., "01_intro_dear_danny_vienna_childhood"
        
        print(f"{doc_name}: {len(doc)} pages")
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Render at 300 DPI for good OCR quality
            mat = fitz.Matrix(300/72, 300/72)
            pix = page.get_pixmap(matrix=mat)
            
            # Output filename: docnum_pagenum.png
            output_path = OUTPUT_DIR / f"{doc_name}_p{page_num+1:02d}.png"
            pix.save(str(output_path))
            total_pages += 1
        
        doc.close()
    
    print(f"\nExtracted {total_pages} page images to {OUTPUT_DIR}/")

if __name__ == "__main__":
    extract_pages()
