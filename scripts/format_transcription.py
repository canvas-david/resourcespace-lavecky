#!/usr/bin/env python3
"""
Format literal transcriptions into reader-friendly versions.

Takes a literal transcription and creates a formatted version with:
- Proper sentence structure and punctuation
- Paragraph breaks for readability
- Preserved author voice and word choices
- [unclear] markers converted to [...]

Usage:
    format_transcription.py --input literal.txt --output formatted.txt
    format_transcription.py --input-dir dir/ --output-dir dir/
"""

import argparse
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("format_transcription")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-sonnet-4-20250514"

FORMAT_PROMPT = """You are formatting a literal transcription of a handwritten memoir letter for readability.

TASK: Add punctuation, capitalization, and paragraph breaks while preserving the author's exact words.

RULES:
1. DO NOT change any words - preserve the author's vocabulary exactly
2. Add periods, commas, and other punctuation where natural
3. Capitalize sentence beginnings and proper nouns
4. Add paragraph breaks at topic transitions (every 3-5 sentences typically)
5. Convert [unclear] markers to [...] 
6. Keep the informal, personal tone of the letter
7. Numbers can stay as digits (1942, 50°, etc.)

EXAMPLE:
Input: "1942 the germans advanced we had to flee barbara had a little ford"
Output: "1942. The Germans advanced. We had to flee. Barbara had a little Ford."

OUTPUT: Return ONLY the formatted text, nothing else.

---

TEXT TO FORMAT:

{text}

---

FORMATTED TEXT:"""


def format_text(text: str, api_key: str) -> str:
    """Format text using Claude."""
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 4096,
        "messages": [
            {"role": "user", "content": FORMAT_PROMPT.format(text=text)}
        ]
    }
    
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(CLAUDE_API_URL, data=data, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result.get("content", [])
            if content and content[0].get("type") == "text":
                return content[0].get("text", "").strip()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Claude API error {e.code}: {e.read().decode()}")
    
    return text


def main():
    parser = argparse.ArgumentParser(description="Format literal transcriptions")
    parser.add_argument("--input", "-i", help="Input file")
    parser.add_argument("--output", "-o", help="Output file")
    parser.add_argument("--input-dir", help="Input directory")
    parser.add_argument("--output-dir", help="Output directory")
    parser.add_argument("--api-key", default=os.getenv("ANTHROPIC_API_KEY"))
    
    args = parser.parse_args()
    
    if not args.api_key:
        logger.error("ANTHROPIC_API_KEY required")
        return 1
    
    if args.input_dir:
        input_dir = Path(args.input_dir)
        output_dir = Path(args.output_dir) if args.output_dir else input_dir.parent / "formatted"
        output_dir.mkdir(exist_ok=True)
        
        for f in sorted(input_dir.glob("*.txt")):
            out_path = output_dir / f.name
            if out_path.exists():
                logger.info(f"Skipping {f.name} (exists)")
                continue
            
            logger.info(f"Formatting {f.name}...")
            text = f.read_text(encoding="utf-8")
            formatted = format_text(text, args.api_key)
            out_path.write_text(formatted, encoding="utf-8")
            logger.info(f"  -> {out_path}")
    
    elif args.input:
        text = Path(args.input).read_text(encoding="utf-8")
        logger.info(f"Formatting {args.input} ({len(text)} chars)...")
        formatted = format_text(text, args.api_key)
        
        if args.output:
            Path(args.output).write_text(formatted, encoding="utf-8")
            logger.info(f"Written to {args.output}")
        else:
            print(formatted)
    
    else:
        parser.error("Provide --input or --input-dir")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
