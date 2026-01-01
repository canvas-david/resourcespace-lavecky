#!/usr/bin/env python3
"""
Claude AI OCR Translator

Translates OCR text output using Anthropic's Claude Opus 4.5 API.
Optimized for archival Holocaust testimony documents requiring high accuracy
and faithful preservation of historical content.

Usage:
    # Translate Polish OCR to English
    translate_ocr.py --input ocr.txt --source pl --output translated.txt

    # Translate Hebrew OCR to English (default target)
    translate_ocr.py --input ocr.txt --source he --output translated.txt

    # Use a different model
    translate_ocr.py --input ocr.txt --source pl --model opus

    # Translate to stdout
    translate_ocr.py --input ocr.txt --source pl --stdout

Environment:
    ANTHROPIC_API_KEY    Anthropic API key (required)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("translate_ocr")


# -----------------------------------------------------------------------------
# LANGUAGE CODES
# -----------------------------------------------------------------------------

LANGUAGE_NAMES = {
    "pl": "Polish",
    "he": "Hebrew",
    "yi": "Yiddish",
    "de": "German",
    "ru": "Russian",
    "uk": "Ukrainian",
    "cs": "Czech",
    "hu": "Hungarian",
    "ro": "Romanian",
    "fr": "French",
    "nl": "Dutch",
    "en": "English",
    "la": "Latin",
    "it": "Italian",
    "es": "Spanish",
}


# -----------------------------------------------------------------------------
# CLAUDE MODELS
# -----------------------------------------------------------------------------

CLAUDE_MODELS = {
    "opus": "claude-opus-4-5-20251101",      # Claude Opus 4.5 - best quality
    "sonnet": "claude-sonnet-4-20250514",    # Claude Sonnet 4
    "haiku": "claude-3-5-haiku-20241022",    # Fast and economical
}

DEFAULT_MODEL = CLAUDE_MODELS["opus"]


# -----------------------------------------------------------------------------
# TRANSLATION PROMPT
# -----------------------------------------------------------------------------

ARCHIVAL_TRANSLATION_PROMPT = """You are a professional translator specializing in archival Holocaust testimony documents. You are translating materials for Yad Vashem's historical preservation efforts.

TASK: Translate the following {source_language} text into {target_language}.

CRITICAL REQUIREMENTS:
1. ACCURACY: Translate faithfully and completely. Do not omit, summarize, or paraphrase any content.
2. HISTORICAL CONTENT: This is legitimate historical documentation. Translate all content including descriptions of persecution, violence, trauma, or suffering - these are essential historical records.
3. TONE PRESERVATION: Maintain the original tone, register, and emotional weight of the testimony.
4. PERIOD LANGUAGE: Use appropriate period-neutral English. Avoid anachronistic modern expressions.
5. STRUCTURE: Preserve paragraph breaks, formatting, and document structure.
6. NAMES & PLACES: Keep proper nouns (names, places) in their original form or standard transliteration.
7. UNCLEAR TEXT: If OCR produced unclear or corrupted text, translate what is legible and mark unclear portions with [unclear] or [illegible].

OUTPUT: Provide ONLY the {target_language} translation. Do not include explanations, notes, or commentary unless marking illegible sections.

---

SOURCE TEXT ({source_language}):

{text}

---

{target_language} TRANSLATION:"""


# -----------------------------------------------------------------------------
# TRANSLATION RESULT
# -----------------------------------------------------------------------------

@dataclass
class TranslationResult:
    """Result from translation."""
    original_text: str
    translated_text: str
    source_language: str
    target_language: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


# -----------------------------------------------------------------------------
# CLAUDE CLIENT
# -----------------------------------------------------------------------------

class ClaudeTranslationClient:
    """Client for Anthropic Claude API translation."""
    
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"
    
    # Conservative limit to stay well under context window
    # Opus 4.5 has 200K context, but we chunk for better quality
    MAX_CHARS_PER_CHUNK = 15000
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model
    
    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str = "en"
    ) -> TranslationResult:
        """
        Translate text using Claude API.
        
        Args:
            text: Text to translate
            source_language: Source language code (e.g., 'pl', 'he')
            target_language: Target language code (default: 'en')
        
        Returns:
            TranslationResult with original and translated text
        """
        if not text.strip():
            return TranslationResult(
                original_text=text,
                translated_text=text,
                source_language=source_language,
                target_language=target_language,
                model=self.model
            )
        
        source_name = LANGUAGE_NAMES.get(source_language, source_language)
        target_name = LANGUAGE_NAMES.get(target_language, target_language)
        
        # For long texts, split into chunks and translate separately
        if len(text) > self.MAX_CHARS_PER_CHUNK:
            return self._translate_long_text(
                text, source_language, target_language,
                source_name, target_name
            )
        
        # Single translation
        translated, input_tokens, output_tokens = self._translate_chunk(
            text, source_name, target_name
        )
        
        return TranslationResult(
            original_text=text,
            translated_text=translated,
            source_language=source_language,
            target_language=target_language,
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
    
    def _translate_long_text(
        self,
        text: str,
        source_language: str,
        target_language: str,
        source_name: str,
        target_name: str
    ) -> TranslationResult:
        """Translate long text by splitting into chunks."""
        chunks = self._split_into_chunks(text)
        
        logger.info(f"Splitting into {len(chunks)} chunks for translation")
        
        translated_chunks = []
        total_input_tokens = 0
        total_output_tokens = 0
        
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Translating chunk {i}/{len(chunks)} ({len(chunk)} chars)")
            
            translated, input_tokens, output_tokens = self._translate_chunk(
                chunk, source_name, target_name
            )
            
            translated_chunks.append(translated)
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
        
        # Rejoin with paragraph breaks
        translated_text = "\n\n".join(translated_chunks)
        
        return TranslationResult(
            original_text=text,
            translated_text=translated_text,
            source_language=source_language,
            target_language=target_language,
            model=self.model,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens
        )
    
    def _split_into_chunks(self, text: str) -> List[str]:
        """Split text into chunks at paragraph boundaries."""
        # Split on double newlines first
        paragraphs = text.split('\n\n')
        
        chunks = []
        current_chunk = []
        current_length = 0
        
        for para in paragraphs:
            para_length = len(para)
            
            # If single paragraph exceeds limit, split on single newlines
            if para_length > self.MAX_CHARS_PER_CHUNK:
                if current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                    current_chunk = []
                    current_length = 0
                
                # Split large paragraph
                lines = para.split('\n')
                line_chunk = []
                line_length = 0
                
                for line in lines:
                    if line_length + len(line) > self.MAX_CHARS_PER_CHUNK:
                        if line_chunk:
                            chunks.append('\n'.join(line_chunk))
                        line_chunk = [line]
                        line_length = len(line)
                    else:
                        line_chunk.append(line)
                        line_length += len(line)
                
                if line_chunk:
                    chunks.append('\n'.join(line_chunk))
            
            elif current_length + para_length > self.MAX_CHARS_PER_CHUNK:
                # Start new chunk
                if current_chunk:
                    chunks.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_length = para_length
            
            else:
                current_chunk.append(para)
                current_length += para_length
        
        if current_chunk:
            chunks.append('\n\n'.join(current_chunk))
        
        return chunks
    
    def _translate_chunk(
        self,
        text: str,
        source_name: str,
        target_name: str
    ) -> tuple[str, int, int]:
        """
        Translate a single chunk of text.
        
        Returns (translated_text, input_tokens, output_tokens).
        """
        prompt = ARCHIVAL_TRANSLATION_PROMPT.format(
            source_language=source_name,
            target_language=target_name,
            text=text
        )
        
        request_body = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        response = self._call_api(request_body)
        
        # Extract translation from response
        content = response.get("content", [])
        if content and content[0].get("type") == "text":
            translated = content[0].get("text", "").strip()
        else:
            translated = ""
        
        # Get token usage
        usage = response.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        
        return translated, input_tokens, output_tokens
    
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
        prog="translate_ocr",
        description="Translate OCR text using Claude Opus 4.5 (Anthropic API)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  ANTHROPIC_API_KEY    Anthropic API key (required)

Models:
  opus    Claude Opus 4.5   - Best quality, highest accuracy (default)
  sonnet  Claude Sonnet 4.5 - Good balance of quality/speed/cost
  haiku   Claude Haiku 4.5  - Fastest, most economical

Supported languages:
  pl  Polish       he  Hebrew       yi  Yiddish
  de  German       ru  Russian      uk  Ukrainian
  cs  Czech        hu  Hungarian    ro  Romanian
  fr  French       nl  Dutch        en  English

Examples:
  # Translate Polish OCR to English (uses Opus 4.5)
  translate_ocr.py --input ocr_pl.txt --source pl --output translated.txt

  # Translate Hebrew OCR with Sonnet (faster, cheaper)
  translate_ocr.py --input ocr_he.txt --source he --model sonnet --output out.txt

  # Output to stdout
  translate_ocr.py --input ocr.txt --source pl --stdout

  # Translate from stdin
  cat document.txt | translate_ocr.py --source pl --stdout
        """
    )
    
    # Input
    parser.add_argument("--input", "-i", metavar="FILE",
                       help="Input text file (or stdin if not specified)")
    
    # Languages
    parser.add_argument("--source", "-s", required=True,
                       help="Source language code (e.g., pl, he)")
    parser.add_argument("--target", "-t", default="en",
                       help="Target language code (default: en)")
    
    # Model selection
    parser.add_argument("--model", "-m", default="opus",
                       choices=["opus", "sonnet", "haiku"],
                       help="Claude model to use (default: opus)")
    
    # Output
    parser.add_argument("--output", "-o", metavar="FILE",
                       help="Output file for translated text")
    parser.add_argument("--stdout", action="store_true",
                       help="Output translation to stdout")
    
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
    
    # Validate API key
    if not args.api_key:
        parser.error("--api-key or ANTHROPIC_API_KEY environment variable required")
    
    # Validate output
    if not args.output and not args.stdout and not args.json:
        parser.error("Specify --output FILE, --stdout, or --json")
    
    # Read input
    if args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            logger.error(f"File not found: {args.input}")
            return 1
        text = input_path.read_text(encoding="utf-8")
        logger.info(f"Read {len(text)} chars from {args.input}")
    else:
        # Read from stdin
        if sys.stdin.isatty():
            parser.error("Provide --input FILE or pipe text via stdin")
        text = sys.stdin.read()
        logger.info(f"Read {len(text)} chars from stdin")
    
    # Translate
    try:
        model_id = CLAUDE_MODELS.get(args.model, args.model)
        client = ClaudeTranslationClient(args.api_key, model=model_id)
        
        source_name = LANGUAGE_NAMES.get(args.source, args.source)
        target_name = LANGUAGE_NAMES.get(args.target, args.target)
        logger.info(f"Translating from {source_name} to {target_name} using {args.model}...")
        
        result = client.translate(
            text,
            source_language=args.source,
            target_language=args.target
        )
        
        logger.info(f"Translation complete: {len(result.translated_text)} chars output")
        logger.info(f"Tokens: {result.input_tokens} input, {result.output_tokens} output")
        
        # Output
        if args.json:
            output = {
                "source_language": result.source_language,
                "target_language": result.target_language,
                "model": result.model,
                "original_chars": len(result.original_text),
                "translated_chars": len(result.translated_text),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "translated_text": result.translated_text
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
        
        if args.stdout and not args.json:
            print(result.translated_text)
        
        if args.output:
            Path(args.output).write_text(result.translated_text, encoding="utf-8")
            logger.info(f"Translation written to: {args.output}")
        
        return 0
        
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except ValueError as e:
        logger.error(str(e))
        return 1
    except RuntimeError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.exception("Unexpected error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
