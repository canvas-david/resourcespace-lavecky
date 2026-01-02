#!/usr/bin/env python3
"""
Claude Vision OCR

Extracts text from images using Claude's vision capabilities.
Simpler alternative to Google Document AI - uses same API as translation.

Usage:
    ocr_claude.py --file image.jpg --output ocr.txt
    ocr_claude.py --file image.jpg --lang pl --stdout

Environment:
    ANTHROPIC_API_KEY    Anthropic API key (required)
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
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
logger = logging.getLogger("ocr_claude")

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
# OCR PROMPT
# -----------------------------------------------------------------------------

OCR_PROMPT = """You are performing OCR (Optical Character Recognition) on an archival document image.

TASK: Extract ALL text visible in this image exactly as written.

CRITICAL REQUIREMENTS:
1. COMPLETENESS: Extract every word, number, and symbol visible in the document.
2. ACCURACY: Preserve the exact spelling, including any historical or non-standard spellings.
3. STRUCTURE: Maintain paragraph breaks and line structure where clear.
4. LANGUAGE: The document is in {language}. Extract the text in its original language - do NOT translate.
5. UNCLEAR TEXT: If text is illegible or unclear, mark it as [illegible] or [unclear].
6. HANDWRITTEN vs TYPED: This appears to be a typewritten document. Extract accordingly.

OUTPUT: Provide ONLY the extracted text. No commentary, no translation, no explanations.

Extract the text now:"""

# -----------------------------------------------------------------------------
# CLAUDE OCR CLIENT
# -----------------------------------------------------------------------------

class ClaudeOCRClient:
    """OCR using Claude's vision capabilities."""
    
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"
    MODEL = "claude-sonnet-4-20250514"
    
    SUPPORTED_TYPES = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def extract_text(self, image_path: str, language: str = "en") -> tuple[str, int, int]:
        """
        Extract text from an image.
        
        Returns (extracted_text, input_tokens, output_tokens).
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        # Check file type
        suffix = path.suffix.lower()
        mime_type = self.SUPPORTED_TYPES.get(suffix)
        if not mime_type:
            raise ValueError(f"Unsupported image type: {suffix}")
        
        # Read and encode image
        with open(path, "rb") as f:
            image_data = base64.standard_b64encode(f.read()).decode("utf-8")
        
        # Build prompt
        lang_name = LANGUAGE_NAMES.get(language, language)
        prompt = OCR_PROMPT.format(language=lang_name)
        
        # Build request
        request_body = {
            "model": self.MODEL,
            "max_tokens": 8192,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": image_data
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        }
        
        response = self._call_api(request_body)
        
        # Extract text from response
        content = response.get("content", [])
        if content and content[0].get("type") == "text":
            text = content[0].get("text", "").strip()
        else:
            text = ""
        
        # Get token usage
        usage = response.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        
        return text, input_tokens, output_tokens
    
    def _call_api(self, body: dict) -> dict:
        """Make API call to Anthropic."""
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json"
        }
        
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.API_URL,
            data=data,
            headers=headers,
            method="POST"
        )
        
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
            raise RuntimeError(f"Claude API error {e.code}: {error_msg}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection failed: {e.reason}")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ocr_claude",
        description="Extract text from images using Claude Vision",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment:
    ANTHROPIC_API_KEY    Anthropic API key (required)

Examples:
    # Extract Polish text from image
    ocr_claude.py --file page_01.jpg --lang pl --output ocr.txt
    
    # Extract Hebrew text to stdout
    ocr_claude.py --file page_21.jpg --lang he --stdout
    
    # JSON output with token counts
    ocr_claude.py --file document.jpg --lang pl --json
        """
    )
    
    parser.add_argument("--file", "-f", required=True,
                       help="Image file path (JPG, PNG, GIF, WebP)")
    parser.add_argument("--lang", "-l", default="en",
                       help="Document language (pl, he, de, etc.)")
    parser.add_argument("--output", "-o", metavar="FILE",
                       help="Output text file")
    parser.add_argument("--stdout", action="store_true",
                       help="Output to stdout")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON")
    parser.add_argument("--api-key", default=os.getenv("ANTHROPIC_API_KEY"),
                       help="Anthropic API key")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if not args.api_key:
        parser.error("--api-key or ANTHROPIC_API_KEY required")
    
    if not args.output and not args.stdout and not args.json:
        parser.error("Specify --output FILE, --stdout, or --json")
    
    try:
        client = ClaudeOCRClient(args.api_key)
        
        logger.info(f"Processing: {args.file}")
        logger.info(f"Language: {LANGUAGE_NAMES.get(args.lang, args.lang)}")
        
        text, input_tokens, output_tokens = client.extract_text(
            args.file, args.lang
        )
        
        logger.info(f"OCR complete: {len(text)} chars extracted")
        logger.info(f"Tokens: {input_tokens} input, {output_tokens} output")
        
        if args.json:
            output = {
                "file": args.file,
                "language": args.lang,
                "chars": len(text),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
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
