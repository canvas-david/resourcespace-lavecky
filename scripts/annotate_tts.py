#!/usr/bin/env python3
"""
TTS Annotation Script

Annotates formatted transcription text with ElevenLabs v3 emotion tags.
Uses a hybrid approach: rule-based patterns + LLM semantic analysis.

Usage:
    # Annotate a file
    annotate_tts.py --input formatted.txt --output tts_script.txt
    
    # Rules only (no LLM, fast & free)
    annotate_tts.py --input formatted.txt --output tts_script.txt --rules-only
    
    # With ResourceSpace API integration
    annotate_tts.py --resource-id 123  # Reads Field 96, writes Field 107
    
    # Pipe through stdin/stdout
    cat formatted.txt | annotate_tts.py --stdout

Environment:
    ANTHROPIC_API_KEY    Required for LLM annotation (not needed with --rules-only)
    RS_BASE_URL          ResourceSpace URL (for --resource-id)
    RS_API_KEY           ResourceSpace API key (for --resource-id)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("annotate_tts")


# -----------------------------------------------------------------------------
# FIELD IDS
# -----------------------------------------------------------------------------

FIELD_FORMATTED_TRANSCRIPTION = 96  # Source: Reader-formatted transcription
FIELD_TTS_SCRIPT = 107              # Target: Emotion-tagged TTS script


# -----------------------------------------------------------------------------
# CLAUDE MODELS
# -----------------------------------------------------------------------------

CLAUDE_MODELS = {
    "opus": "claude-opus-4-5-20251101",
    "sonnet": "claude-sonnet-4-20250514",
    "haiku": "claude-3-5-haiku-20241022",  # Fast and economical
}

DEFAULT_MODEL = CLAUDE_MODELS["haiku"]  # Use Haiku for annotation (cost-effective)


# -----------------------------------------------------------------------------
# TTS ANNOTATION PROMPT
# -----------------------------------------------------------------------------

TTS_ANNOTATION_PROMPT = """You are annotating memoir text for text-to-speech synthesis using ElevenLabs v3.

TASK: Add emotion and delivery tags to this text for an elderly female narrator (grandmother voice).

TAG PLACEMENT RULES:
1. Add tags at the START of emotional passages, not every sentence
2. Start the document with [elderly, warm] for consistent voice
3. Add [pause] between major topic transitions
4. Use delivery tags for specific moments: [sighing], [laughing], [whispering], [tearfully]
5. Don't over-tag - let the natural text carry emotion

AVAILABLE TAGS:
- Emotions: [sad], [nostalgic], [gentle], [worried], [joyful], [wistful], [hopeful], [solemn]
- Delivery: [sighing], [laughing], [whispering], [tearfully], [softly], [warmly]  
- Direction: [elderly, warm], [storytelling], [reminiscing], [thoughtful]
- Pacing: [pause], [slowly]

TEXT MARKERS (already in text, preserve as-is):
- "..." = trailing off (becomes [trailing] if at sentence end)
- "-" = interruption
- Exclamations and questions will be naturally expressive

EXAMPLE:
Input: "Those were happy times. We would walk through the gardens... But then everything changed."
Output: "[elderly, warm] Those were happy times. [nostalgic] We would walk through the gardens... [pause] [sadly] But then everything changed."

OUTPUT: Return ONLY the annotated text. Preserve ALL original text exactly - only ADD tags.

---

TEXT TO ANNOTATE:

{text}

---

ANNOTATED TEXT:"""


# -----------------------------------------------------------------------------
# RESULT TYPES
# -----------------------------------------------------------------------------

@dataclass
class AnnotationResult:
    """Result from annotation."""
    original_text: str
    annotated_text: str
    rules_applied: List[str] = field(default_factory=list)
    llm_used: bool = False
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


# -----------------------------------------------------------------------------
# RULE-BASED ANNOTATION
# -----------------------------------------------------------------------------

class RuleBasedAnnotator:
    """Apply deterministic rule-based annotations."""
    
    def annotate(self, text: str) -> tuple[str, List[str]]:
        """
        Apply rules to text.
        Returns (annotated_text, list_of_rules_applied).
        """
        rules_applied = []
        
        # Start with elderly voice direction if not already tagged
        if not text.strip().startswith('['):
            text = '[elderly, warm] ' + text
            rules_applied.append('start_direction')
        
        # Add [pause] after paragraph breaks (double newlines)
        # But only if no tag already follows
        def add_pause_after_break(match):
            # Check if there's already a tag after the break
            if re.match(r'\s*\[', match.group(2)):
                return match.group(0)
            return match.group(1) + '\n\n[pause] '
        
        text, n = re.subn(r'(\S)(\n\n)(?!\s*\[)', add_pause_after_break, text)
        if n > 0:
            rules_applied.append(f'paragraph_pause:{n}')
        
        # Ellipsis trailing at end of sentence - add [trailing] if followed by punctuation or newline
        text, n = re.subn(r'\.\.\.(\s*)([.!?\n]|$)', r'... [trailing]\1\2', text)
        if n > 0:
            rules_applied.append(f'trailing_ellipsis:{n}')
        
        # Multiple exclamation marks -> [emphatic]
        text, n = re.subn(r'(!{2,})', r'! [emphatic]', text)
        if n > 0:
            rules_applied.append(f'emphatic:{n}')
        
        # Text in ALL CAPS (more than 2 chars) -> [emphasized]
        def caps_to_emphasized(match):
            word = match.group(0)
            # Skip common abbreviations
            if word in ['I', 'A', 'II', 'III', 'IV', 'V', 'USA', 'UK', 'USSR']:
                return word
            return f'[emphasized] {word}'
        
        text, n = re.subn(r'\b[A-Z]{3,}\b', caps_to_emphasized, text)
        if n > 0:
            rules_applied.append(f'caps_emphasized:{n}')
        
        return text, rules_applied


# -----------------------------------------------------------------------------
# LLM ANNOTATION
# -----------------------------------------------------------------------------

class ClaudeAnnotator:
    """Use Claude API for semantic emotion annotation."""
    
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"
    MAX_CHARS_PER_CHUNK = 8000  # Smaller chunks for annotation quality
    
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.api_key = api_key
        self.model = model
    
    def annotate(self, text: str) -> tuple[str, int, int]:
        """
        Annotate text using Claude.
        Returns (annotated_text, input_tokens, output_tokens).
        """
        if not text.strip():
            return text, 0, 0
        
        # For long texts, split and annotate chunks
        if len(text) > self.MAX_CHARS_PER_CHUNK:
            return self._annotate_long_text(text)
        
        return self._annotate_chunk(text)
    
    def _annotate_long_text(self, text: str) -> tuple[str, int, int]:
        """Annotate long text by splitting into chunks."""
        chunks = self._split_into_chunks(text)
        
        logger.info(f"Splitting into {len(chunks)} chunks for annotation")
        
        annotated_chunks = []
        total_input = 0
        total_output = 0
        
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Annotating chunk {i}/{len(chunks)} ({len(chunk)} chars)")
            
            annotated, input_tokens, output_tokens = self._annotate_chunk(chunk)
            annotated_chunks.append(annotated)
            total_input += input_tokens
            total_output += output_tokens
        
        return "\n\n".join(annotated_chunks), total_input, total_output
    
    def _split_into_chunks(self, text: str) -> List[str]:
        """Split text at paragraph boundaries."""
        paragraphs = text.split('\n\n')
        
        chunks = []
        current = []
        current_len = 0
        
        for para in paragraphs:
            if current_len + len(para) > self.MAX_CHARS_PER_CHUNK:
                if current:
                    chunks.append('\n\n'.join(current))
                current = [para]
                current_len = len(para)
            else:
                current.append(para)
                current_len += len(para)
        
        if current:
            chunks.append('\n\n'.join(current))
        
        return chunks
    
    def _annotate_chunk(self, text: str) -> tuple[str, int, int]:
        """Annotate a single chunk."""
        prompt = TTS_ANNOTATION_PROMPT.format(text=text)
        
        request_body = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }
        
        response = self._call_api(request_body)
        
        content = response.get("content", [])
        if content and content[0].get("type") == "text":
            annotated = content[0].get("text", "").strip()
        else:
            annotated = text  # Return original if no response
        
        usage = response.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        
        return annotated, input_tokens, output_tokens
    
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
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                error_json = json.loads(error_body)
                error_msg = error_json.get("error", {}).get("message", error_body)
            except json.JSONDecodeError:
                error_msg = error_body
            raise RuntimeError(f"Claude API error {e.code}: {error_msg}")


# -----------------------------------------------------------------------------
# RESOURCESPACE CLIENT
# -----------------------------------------------------------------------------

class ResourceSpaceClient:
    """Simple client for ResourceSpace API."""
    
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
    
    def _sign(self, query: str) -> str:
        """Generate API signature."""
        return hashlib.sha256((self.api_key + query).encode()).hexdigest()
    
    def _call(self, function: str, params: Dict = None) -> any:
        """Call ResourceSpace API."""
        params = params or {}
        query = f"function={function}"
        for k, v in sorted(params.items()):
            query += f"&{k}={v}"
        
        sign = self._sign(query)
        url = f"{self.base_url}/api/?{query}&sign={sign}"
        
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read().decode("utf-8")
                if data.startswith('"') and data.endswith('"'):
                    return json.loads(data)
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    return data
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"API error {e.code}: {e.read().decode()}")
    
    def get_field(self, resource_id: int, field_id: int) -> str:
        """Get field value for a resource."""
        result = self._call("get_resource_field_data", {"resource": resource_id})
        if isinstance(result, list):
            for f in result:
                if f.get("resource_type_field") == str(field_id):
                    return f.get("value", "")
        return ""
    
    def update_field(self, resource_id: int, field_id: int, value: str) -> bool:
        """Update field value."""
        result = self._call("update_field", {
            "resource": resource_id,
            "field": field_id,
            "value": urllib.parse.quote(value, safe='')
        })
        return result is True or result == "true"


# Import for URL encoding
import urllib.parse


# -----------------------------------------------------------------------------
# MAIN ANNOTATION FUNCTION
# -----------------------------------------------------------------------------

def annotate_text(
    text: str,
    use_llm: bool = True,
    api_key: str = None,
    model: str = DEFAULT_MODEL
) -> AnnotationResult:
    """
    Annotate text with TTS emotion tags.
    
    Args:
        text: Text to annotate
        use_llm: Whether to use LLM (requires api_key)
        api_key: Anthropic API key
        model: Claude model to use
    
    Returns:
        AnnotationResult with annotated text and metadata
    """
    # Step 1: Apply rule-based annotations
    rule_annotator = RuleBasedAnnotator()
    annotated, rules_applied = rule_annotator.annotate(text)
    
    result = AnnotationResult(
        original_text=text,
        annotated_text=annotated,
        rules_applied=rules_applied,
        llm_used=False
    )
    
    # Step 2: Apply LLM annotation if enabled
    if use_llm:
        if not api_key:
            logger.warning("LLM annotation requested but no API key provided")
            return result
        
        try:
            llm_annotator = ClaudeAnnotator(api_key, model)
            annotated, input_tokens, output_tokens = llm_annotator.annotate(annotated)
            
            result.annotated_text = annotated
            result.llm_used = True
            result.model = model
            result.input_tokens = input_tokens
            result.output_tokens = output_tokens
            
        except Exception as e:
            logger.error(f"LLM annotation failed: {e}")
            logger.info("Falling back to rule-based annotation only")
    
    return result


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="annotate_tts",
        description="Annotate text with ElevenLabs v3 emotion tags for TTS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment:
  ANTHROPIC_API_KEY    Anthropic API key (for LLM annotation)
  RS_BASE_URL          ResourceSpace base URL (for --resource-id)
  RS_API_KEY           ResourceSpace API key (for --resource-id)

Examples:
  # Annotate a file with hybrid (rules + LLM)
  annotate_tts.py --input formatted.txt --output tts_script.txt

  # Rules only (fast, free)
  annotate_tts.py --input formatted.txt --output tts_script.txt --rules-only

  # ResourceSpace integration (reads Field 96, writes Field 107)
  RS_BASE_URL="https://..." RS_API_KEY="..." annotate_tts.py --resource-id 123

  # Pipe through stdin/stdout
  cat formatted.txt | annotate_tts.py --stdout --rules-only
        """
    )
    
    # Input sources (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("--input", "-i", metavar="FILE",
                            help="Input text file")
    input_group.add_argument("--resource-id", "-r", type=int,
                            help="ResourceSpace resource ID (reads Field 96)")
    
    # Output targets
    parser.add_argument("--output", "-o", metavar="FILE",
                       help="Output file for annotated text")
    parser.add_argument("--stdout", action="store_true",
                       help="Output to stdout")
    
    # Annotation options
    parser.add_argument("--rules-only", action="store_true",
                       help="Use only rule-based annotation (no LLM)")
    parser.add_argument("--model", "-m", default="haiku",
                       choices=["opus", "sonnet", "haiku"],
                       help="Claude model for LLM annotation (default: haiku)")
    
    # API keys
    parser.add_argument("--api-key", default=os.getenv("ANTHROPIC_API_KEY"),
                       help="Anthropic API key")
    parser.add_argument("--rs-url", default=os.getenv("RS_BASE_URL"),
                       help="ResourceSpace base URL")
    parser.add_argument("--rs-api-key", default=os.getenv("RS_API_KEY"),
                       help="ResourceSpace API key")
    
    # Output format
    parser.add_argument("--json", action="store_true",
                       help="Output result as JSON")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate inputs
    if not args.input and not args.resource_id and sys.stdin.isatty():
        parser.error("Provide --input FILE, --resource-id, or pipe text via stdin")
    
    if not args.output and not args.stdout and not args.json and not args.resource_id:
        parser.error("Specify --output FILE, --stdout, --json, or --resource-id")
    
    # Read input text
    rs_client = None
    if args.resource_id:
        if not args.rs_url or not args.rs_api_key:
            parser.error("--resource-id requires RS_BASE_URL and RS_API_KEY")
        
        rs_client = ResourceSpaceClient(args.rs_url, args.rs_api_key)
        text = rs_client.get_field(args.resource_id, FIELD_FORMATTED_TRANSCRIPTION)
        
        if not text.strip():
            logger.error(f"No formatted transcription found for resource {args.resource_id}")
            return 1
        
        logger.info(f"Read {len(text)} chars from resource {args.resource_id} Field {FIELD_FORMATTED_TRANSCRIPTION}")
    
    elif args.input:
        input_path = Path(args.input)
        if not input_path.exists():
            logger.error(f"File not found: {args.input}")
            return 1
        text = input_path.read_text(encoding="utf-8")
        logger.info(f"Read {len(text)} chars from {args.input}")
    
    else:
        text = sys.stdin.read()
        logger.info(f"Read {len(text)} chars from stdin")
    
    # Annotate
    try:
        use_llm = not args.rules_only
        model_id = CLAUDE_MODELS.get(args.model, args.model)
        
        if use_llm and not args.api_key:
            logger.warning("No ANTHROPIC_API_KEY, falling back to rules-only")
            use_llm = False
        
        logger.info(f"Annotating with {'LLM + rules' if use_llm else 'rules only'}...")
        
        result = annotate_text(
            text,
            use_llm=use_llm,
            api_key=args.api_key,
            model=model_id
        )
        
        logger.info(f"Annotation complete: {len(result.annotated_text)} chars")
        if result.llm_used:
            logger.info(f"LLM tokens: {result.input_tokens} in, {result.output_tokens} out")
        logger.info(f"Rules applied: {', '.join(result.rules_applied) or 'none'}")
        
        # Output
        if args.json:
            output = {
                "original_chars": len(result.original_text),
                "annotated_chars": len(result.annotated_text),
                "rules_applied": result.rules_applied,
                "llm_used": result.llm_used,
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "annotated_text": result.annotated_text
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
        
        if args.stdout and not args.json:
            print(result.annotated_text)
        
        if args.output:
            Path(args.output).write_text(result.annotated_text, encoding="utf-8")
            logger.info(f"Written to: {args.output}")
        
        # Write back to ResourceSpace
        if args.resource_id and rs_client:
            success = rs_client.update_field(
                args.resource_id,
                FIELD_TTS_SCRIPT,
                result.annotated_text
            )
            if success:
                logger.info(f"Updated resource {args.resource_id} Field {FIELD_TTS_SCRIPT}")
            else:
                logger.error(f"Failed to update resource {args.resource_id}")
                return 1
        
        return 0
        
    except Exception as e:
        logger.exception("Annotation failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
