#!/usr/bin/env python3
"""
Google Cloud Vision OCR

Extracts text from images using Google Cloud Vision API.
Uses simple API key authentication (no service account needed).

Usage:
    ocr_google_vision.py --file image.jpg --output ocr.txt
    ocr_google_vision.py --file image.jpg --lang pl --stdout

Environment:
    GOOGLE_API_KEY    Google Cloud API key (required)
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ocr_google_vision")

# -----------------------------------------------------------------------------
# LANGUAGE NAMES
# -----------------------------------------------------------------------------

LANGUAGE_NAMES = {
    "pl": "Polish",
    "he": "Hebrew",
    "yi": "Yiddish",
    "de": "German",
    "ru": "Russian",
    "en": "English",
}

# -----------------------------------------------------------------------------
# GOOGLE VISION CLIENT
# -----------------------------------------------------------------------------

class GoogleVisionOCR:
    """OCR using Google Cloud Vision API with API key."""
    
    API_URL = "https://vision.googleapis.com/v1/images:annotate"
    
    SUPPORTED_TYPES = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".pdf": "application/pdf",
    }
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def extract_text(
        self,
        image_path: str,
        language_hints: Optional[list] = None
    ) -> tuple[str, float]:
        """
        Extract text from an image using Google Cloud Vision.
        
        Returns (extracted_text, confidence).
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        # Check file type
        suffix = path.suffix.lower()
        if suffix not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported image type: {suffix}")
        
        # Read and encode image
        with open(path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        
        # Build request
        request_body = {
            "requests": [
                {
                    "image": {
                        "content": image_data
                    },
                    "features": [
                        {
                            "type": "DOCUMENT_TEXT_DETECTION",
                            "maxResults": 1
                        }
                    ]
                }
            ]
        }
        
        # Add language hints if provided
        if language_hints:
            request_body["requests"][0]["imageContext"] = {
                "languageHints": language_hints
            }
        
        # Make API call
        response = self._call_api(request_body)
        
        # Parse response
        return self._parse_response(response)
    
    def _call_api(self, body: dict) -> dict:
        """Make API call to Google Vision."""
        url = f"{self.API_URL}?key={self.api_key}"
        
        headers = {
            "Content-Type": "application/json"
        }
        
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                error_json = json.loads(error_body)
                error_msg = error_json.get("error", {}).get("message", error_body)
            except json.JSONDecodeError:
                error_msg = error_body
            raise RuntimeError(f"Google Vision API error {e.code}: {error_msg}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection failed: {e.reason}")
    
    def _parse_response(self, response: dict) -> tuple[str, float]:
        """Parse Google Vision API response."""
        responses = response.get("responses", [])
        if not responses:
            return "", 0.0
        
        result = responses[0]
        
        # Check for errors
        if "error" in result:
            error = result["error"]
            raise RuntimeError(f"Vision API error: {error.get('message', str(error))}")
        
        # Get full text annotation
        full_text = result.get("fullTextAnnotation", {})
        text = full_text.get("text", "")
        
        # Calculate average confidence from pages
        pages = full_text.get("pages", [])
        confidences = []
        for page in pages:
            for block in page.get("blocks", []):
                if "confidence" in block:
                    confidences.append(block["confidence"])
        
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        return text, avg_confidence


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ocr_google_vision",
        description="Extract text from images using Google Cloud Vision API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment:
    GOOGLE_API_KEY    Google Cloud API key (required)

Examples:
    # Extract text from image
    ocr_google_vision.py --file page_01.jpg --output ocr.txt
    
    # With language hint for better accuracy
    ocr_google_vision.py --file page_01.jpg --lang pl --output ocr.txt
    
    # Output to stdout
    ocr_google_vision.py --file page_01.jpg --stdout
    
    # JSON output with confidence score
    ocr_google_vision.py --file page_01.jpg --json
        """
    )
    
    parser.add_argument("--file", "-f", required=True,
                       help="Image file path (JPG, PNG, TIFF, PDF, etc.)")
    parser.add_argument("--lang", "-l",
                       help="Language hint for better accuracy (pl, he, de, etc.)")
    parser.add_argument("--output", "-o", metavar="FILE",
                       help="Output text file")
    parser.add_argument("--stdout", action="store_true",
                       help="Output to stdout")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON with confidence")
    parser.add_argument("--api-key", default=os.getenv("GOOGLE_API_KEY"),
                       help="Google API key (or GOOGLE_API_KEY env var)")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if not args.api_key:
        parser.error("--api-key or GOOGLE_API_KEY required")
    
    if not args.output and not args.stdout and not args.json:
        parser.error("Specify --output FILE, --stdout, or --json")
    
    try:
        client = GoogleVisionOCR(args.api_key)
        
        logger.info(f"Processing: {args.file}")
        if args.lang:
            logger.info(f"Language hint: {LANGUAGE_NAMES.get(args.lang, args.lang)}")
        
        language_hints = [args.lang] if args.lang else None
        text, confidence = client.extract_text(args.file, language_hints)
        
        logger.info(f"OCR complete: {len(text)} chars extracted")
        logger.info(f"Confidence: {confidence:.1%}")
        
        if args.json:
            output = {
                "file": args.file,
                "language": args.lang,
                "chars": len(text),
                "confidence": confidence,
                "text": text
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
        
        if args.stdout and not args.json:
            print(text)
        
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
            logger.info(f"Text written to: {args.output}")
        
        return 0
        
    except Exception as e:
        logger.error(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
