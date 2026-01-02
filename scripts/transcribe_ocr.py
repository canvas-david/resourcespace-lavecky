#!/usr/bin/env python3
"""
Claude AI OCR Transcription Corrector

Converts raw OCR output into verified literal transcription using Claude's
vision capabilities to compare against original scans.

This script maintains archival integrity by:
- Correcting only OCR errors (machine misreadings)
- Preserving the author's original words, spelling, and style
- Marking unclear or illegible portions explicitly
- Never interpreting or modernizing content

Usage:
    # Correct OCR using original scan for verification
    transcribe_ocr.py --ocr raw_ocr.txt --scan page.pdf --output literal.txt

    # Process without scan (OCR-only correction, less accurate)
    transcribe_ocr.py --ocr raw_ocr.txt --output literal.txt

    # Output to stdout
    transcribe_ocr.py --ocr raw_ocr.txt --scan page.jpg --stdout

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
from dataclasses import dataclass
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
logger = logging.getLogger("transcribe_ocr")


# -----------------------------------------------------------------------------
# CLAUDE MODELS
# -----------------------------------------------------------------------------

CLAUDE_MODELS = {
    "opus": "claude-opus-4-5-20251101",
    "sonnet": "claude-sonnet-4-20250514",
}

DEFAULT_MODEL = CLAUDE_MODELS["opus"]


# -----------------------------------------------------------------------------
# ARCHIVAL TRANSCRIPTION PROMPT
# -----------------------------------------------------------------------------

ARCHIVAL_TRANSCRIPTION_PROMPT = """You are an archival transcription specialist. Your task is to produce an accurate LITERAL TRANSCRIPTION from OCR output, correcting only machine-reading errors while preserving the author's original words exactly.

CONTEXT: This is a handwritten personal memoir/letter. The OCR was performed by machine and contains errors. You must correct these errors by comparing to what was actually written, but you must NOT change the author's original words, spelling choices, or style.

TASK: Produce a literal transcription that corrects OCR errors only.

CRITICAL REQUIREMENTS:

1. CORRECT OCR ERRORS ONLY
   - Fix obvious machine misreadings (e.g., "Dummy" → "Danny" if the handwriting shows "Danny")
   - Fix character substitutions (e.g., "méinories" → "memories")
   - Fix word fragmentations caused by line-break detection
   - Fix garbled text from handwriting recognition failures

2. PRESERVE THE AUTHOR'S ORIGINAL TEXT
   - Keep the author's spelling choices (British vs American, period-appropriate)
   - Keep the author's grammar, even if unconventional
   - Keep the author's punctuation style
   - Keep the author's word choices (don't substitute synonyms)
   - Keep idiomatic expressions even if unusual

3. PRESERVE STRUCTURE
   - Maintain paragraph breaks as written
   - Preserve the flow and grouping of thoughts
   - Keep emphasis (underlines, capitals) as intended

4. MARK UNCERTAINTIES
   - [unclear] - text is present but cannot be read with confidence
   - [illegible] - text cannot be determined at all
   - [word?] - best guess with uncertainty marker
   - [...] - indicates omitted/missing content

5. DO NOT:
   - Add interpretations or context
   - Modernize language or expressions
   - "Fix" the author's grammar or style
   - Summarize or paraphrase
   - Add punctuation the author didn't use
   - Remove punctuation the author did use

OUTPUT FORMAT:
- Provide ONLY the corrected transcription
- Do not include explanations, notes, or commentary
- Do not add headers or metadata
- Preserve blank lines between paragraphs

---

RAW OCR TEXT:

{ocr_text}

---

LITERAL TRANSCRIPTION:"""


ARCHIVAL_TRANSCRIPTION_PROMPT_WITH_IMAGE = """You are an archival transcription specialist. Your task is to produce an accurate LITERAL TRANSCRIPTION by comparing the raw OCR output against the original handwritten document image.

CONTEXT: This is a handwritten personal memoir/letter. The OCR was performed by machine and contains errors. You have access to both the OCR output AND the original scan. Use the image to verify and correct the OCR.

TASK: Produce a literal transcription that accurately reflects what was written.

CRITICAL REQUIREMENTS:

1. COMPARE OCR TO IMAGE
   - Use the image as the source of truth
   - Correct any OCR misreadings you can identify
   - If the image is clearer than OCR suggests, use the image
   - If parts of the image are unclear, mark appropriately

2. CORRECT OCR ERRORS ONLY
   - Fix obvious machine misreadings by checking the image
   - Fix character substitutions visible in the scan
   - Fix word fragmentations caused by line-break detection
   - Fix garbled text from handwriting recognition failures

3. PRESERVE THE AUTHOR'S ORIGINAL TEXT
   - Keep the author's spelling choices (British vs American, period-appropriate)
   - Keep the author's grammar, even if unconventional
   - Keep the author's punctuation style
   - Keep the author's word choices (don't substitute synonyms)
   - Keep idiomatic expressions even if unusual

4. PRESERVE STRUCTURE
   - Maintain paragraph breaks as written in the original
   - Preserve the flow and grouping of thoughts
   - Keep emphasis (underlines, capitals) as shown in image

5. MARK UNCERTAINTIES
   - [unclear] - text is present but cannot be read with confidence
   - [illegible] - text cannot be determined at all
   - [word?] - best guess with uncertainty marker
   - [...] - indicates omitted/missing content

6. DO NOT:
   - Add interpretations or context
   - Modernize language or expressions
   - "Fix" the author's grammar or style
   - Summarize or paraphrase
   - Add punctuation the author didn't use
   - Remove punctuation the author did use

OUTPUT FORMAT:
- Provide ONLY the corrected transcription
- Do not include explanations, notes, or commentary
- Do not add headers or metadata
- Preserve blank lines between paragraphs

---

RAW OCR TEXT:

{ocr_text}

---

LITERAL TRANSCRIPTION (comparing OCR to the image provided):"""


# -----------------------------------------------------------------------------
# TRANSCRIPTION RESULT
# -----------------------------------------------------------------------------

@dataclass
class TranscriptionResult:
    """Result from transcription correction."""
    raw_ocr: str
    literal_transcription: str
    had_image: bool
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


# -----------------------------------------------------------------------------
# CLAUDE CLIENT
# -----------------------------------------------------------------------------

class ClaudeTranscriptionClient:
    """Client for Anthropic Claude API transcription correction."""
    
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model
    
    def transcribe(
        self,
        ocr_text: str,
        image_path: Optional[Path] = None
    ) -> TranscriptionResult:
        """
        Correct OCR text to produce literal transcription.
        
        Args:
            ocr_text: Raw OCR output text
            image_path: Optional path to original scan for verification
        
        Returns:
            TranscriptionResult with corrected transcription
        """
        if not ocr_text.strip():
            return TranscriptionResult(
                raw_ocr=ocr_text,
                literal_transcription=ocr_text,
                had_image=False,
                model=self.model
            )
        
        if image_path and image_path.exists():
            return self._transcribe_with_image(ocr_text, image_path)
        else:
            return self._transcribe_text_only(ocr_text)
    
    def _transcribe_text_only(self, ocr_text: str) -> TranscriptionResult:
        """Correct OCR without reference image."""
        prompt = ARCHIVAL_TRANSCRIPTION_PROMPT.format(ocr_text=ocr_text)
        
        request_body = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        response = self._call_api(request_body)
        transcription = self._extract_text(response)
        usage = response.get("usage", {})
        
        return TranscriptionResult(
            raw_ocr=ocr_text,
            literal_transcription=transcription,
            had_image=False,
            model=self.model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0)
        )
    
    def _transcribe_with_image(
        self,
        ocr_text: str,
        image_path: Path
    ) -> TranscriptionResult:
        """Correct OCR using reference image for verification."""
        # Read and encode image
        image_data = image_path.read_bytes()
        image_b64 = base64.standard_b64encode(image_data).decode("ascii")
        
        # Determine media type
        mime_type, _ = mimetypes.guess_type(str(image_path))
        if mime_type not in ["image/jpeg", "image/png", "image/gif", "image/webp"]:
            # For PDFs, we'd need to convert - for now, fall back to text-only
            if image_path.suffix.lower() == ".pdf":
                logger.warning("PDF images require conversion; falling back to text-only")
                return self._transcribe_text_only(ocr_text)
            mime_type = "image/jpeg"  # Default assumption
        
        prompt = ARCHIVAL_TRANSCRIPTION_PROMPT_WITH_IMAGE.format(ocr_text=ocr_text)
        
        request_body = {
            "model": self.model,
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
                                "data": image_b64
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
        transcription = self._extract_text(response)
        usage = response.get("usage", {})
        
        return TranscriptionResult(
            raw_ocr=ocr_text,
            literal_transcription=transcription,
            had_image=True,
            model=self.model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0)
        )
    
    def _extract_text(self, response: dict) -> str:
        """Extract text content from API response."""
        content = response.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0].get("text", "").strip()
        return ""
    
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
            with urllib.request.urlopen(req, timeout=300) as resp:
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
        prog="transcribe_ocr",
        description="Convert raw OCR to literal transcription using Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  ANTHROPIC_API_KEY    Anthropic API key (required)

Models:
  opus    Claude Opus 4.5   - Best accuracy for handwriting (default)
  sonnet  Claude Sonnet 4   - Faster, good for clear text

This script produces LITERAL transcriptions that:
  - Correct OCR machine errors only
  - Preserve the author's original words, spelling, grammar
  - Mark unclear/illegible sections appropriately
  - Do NOT interpret, modernize, or "improve" the text

Examples:
  # Correct OCR with original scan for verification (best accuracy)
  transcribe_ocr.py --ocr raw.txt --scan page.jpg --output literal.txt

  # Correct OCR without scan (less accurate)
  transcribe_ocr.py --ocr raw.txt --output literal.txt

  # Process multiple pages
  for f in ocr/*.txt; do
    transcribe_ocr.py --ocr "$f" --output "literal/$(basename $f)"
  done
        """
    )
    
    # Input
    parser.add_argument("--ocr", "-i", required=True, metavar="FILE",
                       help="Raw OCR text file")
    parser.add_argument("--scan", "-s", metavar="FILE",
                       help="Original scan image (jpg, png) for verification")
    
    # Model
    parser.add_argument("--model", "-m", default="opus",
                       choices=["opus", "sonnet"],
                       help="Claude model to use (default: opus)")
    
    # Output
    parser.add_argument("--output", "-o", metavar="FILE",
                       help="Output file for literal transcription")
    parser.add_argument("--stdout", action="store_true",
                       help="Output transcription to stdout")
    
    # Options
    parser.add_argument("--json", action="store_true",
                       help="Output result as JSON")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    parser.add_argument("--api-key", default=os.getenv("ANTHROPIC_API_KEY"),
                       help="Anthropic API key (or ANTHROPIC_API_KEY env var)")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate
    if not args.api_key:
        parser.error("--api-key or ANTHROPIC_API_KEY environment variable required")
    
    if not args.output and not args.stdout and not args.json:
        parser.error("Specify --output FILE, --stdout, or --json")
    
    ocr_path = Path(args.ocr)
    if not ocr_path.exists():
        logger.error(f"OCR file not found: {args.ocr}")
        return 1
    
    scan_path = Path(args.scan) if args.scan else None
    if scan_path and not scan_path.exists():
        logger.warning(f"Scan file not found: {args.scan} - proceeding without image")
        scan_path = None
    
    # Read OCR
    ocr_text = ocr_path.read_text(encoding="utf-8")
    logger.info(f"Read {len(ocr_text)} chars from {args.ocr}")
    
    if scan_path:
        logger.info(f"Using scan for verification: {scan_path}")
    else:
        logger.info("No scan provided - OCR-only correction (less accurate)")
    
    # Process
    try:
        model_id = CLAUDE_MODELS.get(args.model, args.model)
        client = ClaudeTranscriptionClient(args.api_key, model=model_id)
        
        logger.info(f"Processing with {args.model}...")
        result = client.transcribe(ocr_text, scan_path)
        
        logger.info(f"Transcription complete: {len(result.literal_transcription)} chars")
        logger.info(f"Tokens: {result.input_tokens} input, {result.output_tokens} output")
        logger.info(f"Image verification: {'Yes' if result.had_image else 'No'}")
        
        # Output
        if args.json:
            output = {
                "model": result.model,
                "had_image": result.had_image,
                "raw_ocr_chars": len(result.raw_ocr),
                "transcription_chars": len(result.literal_transcription),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "literal_transcription": result.literal_transcription
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
        
        if args.stdout and not args.json:
            print(result.literal_transcription)
        
        if args.output:
            Path(args.output).write_text(
                result.literal_transcription, encoding="utf-8"
            )
            logger.info(f"Transcription written to: {args.output}")
        
        return 0
        
    except Exception as e:
        logger.error(str(e))
        if args.debug:
            logger.exception("Full traceback")
        return 1


if __name__ == "__main__":
    sys.exit(main())
