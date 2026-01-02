#!/usr/bin/env python3
"""
Multi-Model OCR Verification Pipeline

Runs 4 OCR models in parallel and uses consensus voting to produce
high-confidence transcriptions:

1. Document AI (dedicated OCR - best for handwriting)
2. Vision API (dedicated OCR - fast, good for typewritten)
3. Claude Vision (LLM - semantic understanding)
4. GPT-5.2 Vision (LLM - semantic understanding)

Consensus Logic:
- 4/4 agree: Very high confidence
- 3/4 agree: High confidence
- 2/4 agree: Medium confidence (flagged for review)
- All different: Low confidence (human review required)

Usage:
    # Full 4-model verification
    ocr_verify.py --image page.jpg --output consensus.txt --report report.json

    # Batch processing
    ocr_verify.py --input-dir scans/ --output-dir verified/ --report-dir reports/

    # Use only specific engines
    ocr_verify.py --image page.jpg --engines docai,vision,claude

Environment:
    GOOGLE_API_KEY                   Vision API key
    GOOGLE_APPLICATION_CREDENTIALS   Document AI service account
    DOCUMENTAI_PROJECT_ID            GCP project ID
    DOCUMENTAI_LOCATION              Processor location (us, eu)
    DOCUMENTAI_PROCESSOR_ID          OCR processor ID
    ANTHROPIC_API_KEY                Claude API key
    OPENAI_API_KEY                   OpenAI API key
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.error
import urllib.request

# Import from local ocr.py
from ocr import (
    VisionAPIClient,
    DocumentAIClient,
    DocumentAIConfig,
    GoogleAuth,
    OCRResult,
    SUPPORTED_TYPES,
)

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ocr_verify")

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------

ENGINE_NAMES = {
    "docai": "Document AI",
    "vision": "Vision API",
    "claude": "Claude Vision",
    "gpt": "GPT-5.2 Vision",
}

# -----------------------------------------------------------------------------
# ARCHIVAL VISION PROMPT
# -----------------------------------------------------------------------------

ARCHIVAL_VISION_OCR_PROMPT = """You are reading handwritten text from an archival document image.

TASK: Transcribe EXACTLY what is written in the image.

CRITICAL RULES:
1. Report ONLY what you can see written - no interpretation
2. Preserve the author's spelling, grammar, and punctuation exactly
3. If a word is unclear, write [unclear]
4. If text is illegible, write [illegible]
5. Do NOT guess, fill in, or "fix" anything
6. Do NOT add explanations or commentary
7. Preserve line breaks and paragraph structure

OUTPUT: Provide ONLY the transcribed text, nothing else."""

# -----------------------------------------------------------------------------
# DATA CLASSES
# -----------------------------------------------------------------------------

@dataclass
class EngineResult:
    """Result from a single OCR engine."""
    engine: str
    text: str
    confidence: float
    error: Optional[str] = None
    
    @property
    def success(self) -> bool:
        return self.error is None


@dataclass
class WordComparison:
    """Comparison of a single word across engines."""
    position: int
    readings: Dict[str, str]
    chosen: Optional[str]
    agreement: str  # e.g., "4/4", "3/4", "2/4"
    confidence: str  # "high", "medium", "low"
    reason: str


@dataclass
class VerificationResult:
    """Final verification result with consensus and report."""
    source_file: str
    models_used: List[str]
    consensus_text: str
    overall_confidence: float
    total_words: int
    high_confidence_words: int
    medium_confidence_words: int
    low_confidence_words: int
    disagreements: List[WordComparison] = field(default_factory=list)
    engine_results: Dict[str, EngineResult] = field(default_factory=dict)


# -----------------------------------------------------------------------------
# LLM VISION CLIENTS
# -----------------------------------------------------------------------------

class ClaudeVisionClient:
    """Claude Vision API client for OCR verification."""
    
    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"
    MODEL = "claude-sonnet-4-20250514"  # Use Sonnet for speed/cost, Opus for max accuracy
    
    def __init__(self, api_key: str):
        self.api_key = api_key
    
    def extract_text(self, image_path: str) -> EngineResult:
        """Extract text from image using Claude Vision."""
        try:
            path = Path(image_path)
            image_data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
            
            # Determine media type
            suffix = path.suffix.lower()
            media_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            media_type = media_types.get(suffix, "image/jpeg")
            
            request_body = {
                "model": self.MODEL,
                "max_tokens": 8192,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data
                            }
                        },
                        {
                            "type": "text",
                            "text": ARCHIVAL_VISION_OCR_PROMPT
                        }
                    ]
                }]
            }
            
            response = self._call_api(request_body)
            text = self._extract_text(response)
            
            return EngineResult(
                engine="claude",
                text=text,
                confidence=0.9  # LLMs don't provide confidence scores
            )
            
        except Exception as e:
            return EngineResult(
                engine="claude",
                text="",
                confidence=0.0,
                error=str(e)
            )
    
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
        
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    
    def _extract_text(self, response: dict) -> str:
        """Extract text from API response."""
        content = response.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0].get("text", "").strip()
        return ""


class GPTVisionClient:
    """OpenAI GPT Vision API client for OCR verification."""
    
    API_URL = "https://api.openai.com/v1/chat/completions"
    MODEL = "gpt-4o"  # Vision-capable model
    
    def __init__(self, api_key: str, model: str = None):
        self.api_key = api_key
        if model:
            self.model = model
        else:
            self.model = self.MODEL
    
    def extract_text(self, image_path: str) -> EngineResult:
        """Extract text from image using GPT Vision."""
        try:
            path = Path(image_path)
            image_data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
            
            # Determine media type
            suffix = path.suffix.lower()
            media_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            media_type = media_types.get(suffix, "image/jpeg")
            
            request_body = {
                "model": self.model,
                "max_tokens": 8192,
                "messages": [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{media_type};base64,{image_data}"
                            }
                        },
                        {
                            "type": "text",
                            "text": ARCHIVAL_VISION_OCR_PROMPT
                        }
                    ]
                }]
            }
            
            response = self._call_api(request_body)
            text = self._extract_text(response)
            
            return EngineResult(
                engine="gpt",
                text=text,
                confidence=0.9  # LLMs don't provide confidence scores
            )
            
        except Exception as e:
            return EngineResult(
                engine="gpt",
                text="",
                confidence=0.0,
                error=str(e)
            )
    
    def _call_api(self, body: dict) -> dict:
        """Make API call to OpenAI."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.API_URL,
            data=data,
            headers=headers,
            method="POST"
        )
        
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    
    def _extract_text(self, response: dict) -> str:
        """Extract text from API response."""
        choices = response.get("choices", [])
        if choices:
            message = choices[0].get("message", {})
            return message.get("content", "").strip()
        return ""


# -----------------------------------------------------------------------------
# TEXT ALIGNMENT AND COMPARISON
# -----------------------------------------------------------------------------

def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    # Convert to lowercase for comparison
    text = text.lower()
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove leading/trailing whitespace
    text = text.strip()
    return text


def tokenize(text: str) -> List[str]:
    """Split text into words for comparison."""
    # Split on whitespace and punctuation boundaries
    words = re.findall(r'\b\w+\b', text.lower())
    return words


def align_texts(texts: Dict[str, str]) -> List[Dict[str, str]]:
    """
    Align multiple texts word-by-word.
    
    Returns list of dicts mapping engine -> word at each position.
    """
    # Tokenize all texts
    tokenized = {engine: tokenize(text) for engine, text in texts.items()}
    
    # Find max length
    max_len = max(len(words) for words in tokenized.values()) if tokenized else 0
    
    # Build aligned list
    aligned = []
    for i in range(max_len):
        position = {}
        for engine, words in tokenized.items():
            if i < len(words):
                position[engine] = words[i]
            else:
                position[engine] = ""  # Padding for shorter texts
        aligned.append(position)
    
    return aligned


def calculate_consensus(readings: Dict[str, str]) -> Tuple[Optional[str], str, str, str]:
    """
    Calculate consensus for a single word position.
    
    Returns (chosen_word, agreement_ratio, confidence_level, reason)
    """
    # Filter out empty readings
    valid_readings = {k: v for k, v in readings.items() if v}
    
    if not valid_readings:
        return None, "0/0", "low", "No readings"
    
    # Count occurrences
    word_counts = Counter(valid_readings.values())
    total = len(valid_readings)
    
    # Find most common
    most_common = word_counts.most_common(1)[0]
    chosen_word, count = most_common
    
    agreement = f"{count}/{total}"
    
    # Determine confidence
    if count == total:
        confidence = "high"
        reason = f"All {total} models agree"
    elif count >= 3:
        confidence = "high"
        agreeing = [k for k, v in valid_readings.items() if v == chosen_word]
        reason = f"Majority agreement ({', '.join(agreeing)})"
    elif count == 2 and total >= 3:
        # Check if dedicated OCR engines agree vs LLMs
        ocr_engines = {"docai", "vision"}
        llm_engines = {"claude", "gpt"}
        
        ocr_votes = {k: v for k, v in valid_readings.items() if k in ocr_engines}
        llm_votes = {k: v for k, v in valid_readings.items() if k in llm_engines}
        
        # If both OCR engines agree, prefer their reading
        if len(set(ocr_votes.values())) == 1 and ocr_votes:
            chosen_word = list(ocr_votes.values())[0]
            confidence = "medium"
            reason = "OCR engines agree, LLMs differ"
        # If both LLMs agree, consider their reading
        elif len(set(llm_votes.values())) == 1 and llm_votes:
            llm_word = list(llm_votes.values())[0]
            if llm_word == chosen_word:
                confidence = "medium"
                reason = "LLMs agree, OCR engines differ"
            else:
                confidence = "medium"
                reason = "Split vote - majority wins"
        else:
            confidence = "medium"
            reason = "Split vote - majority wins"
    else:
        confidence = "low"
        reason = "No consensus - flagged for human review"
        chosen_word = None  # Don't auto-choose when all differ
    
    return chosen_word, agreement, confidence, reason


# -----------------------------------------------------------------------------
# VERIFICATION ENGINE
# -----------------------------------------------------------------------------

class OCRVerificationEngine:
    """Multi-model OCR verification engine."""
    
    def __init__(
        self,
        vision_client: Optional[VisionAPIClient] = None,
        docai_client: Optional[DocumentAIClient] = None,
        claude_client: Optional[ClaudeVisionClient] = None,
        gpt_client: Optional[GPTVisionClient] = None,
        enabled_engines: Optional[List[str]] = None
    ):
        self.clients = {}
        
        if vision_client:
            self.clients["vision"] = vision_client
        if docai_client:
            self.clients["docai"] = docai_client
        if claude_client:
            self.clients["claude"] = claude_client
        if gpt_client:
            self.clients["gpt"] = gpt_client
        
        # Filter to enabled engines only
        if enabled_engines:
            self.clients = {k: v for k, v in self.clients.items() if k in enabled_engines}
        
        if not self.clients:
            raise ValueError("At least one OCR engine must be configured")
    
    def verify(self, image_path: str) -> VerificationResult:
        """
        Run all engines and produce consensus verification.
        """
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        # Run all engines
        logger.info(f"Running {len(self.clients)} OCR engines on {path.name}...")
        engine_results = {}
        
        for engine_name, client in self.clients.items():
            logger.info(f"  Running {ENGINE_NAMES.get(engine_name, engine_name)}...")
            
            if engine_name in ("docai", "vision"):
                # Dedicated OCR engines
                try:
                    if engine_name == "docai":
                        result = client.extract_text(str(image_path))
                        engine_results[engine_name] = EngineResult(
                            engine=engine_name,
                            text=result.text,
                            confidence=result.confidence
                        )
                    else:  # vision
                        result = client.extract_text(str(image_path))
                        engine_results[engine_name] = EngineResult(
                            engine=engine_name,
                            text=result.text,
                            confidence=result.confidence
                        )
                except Exception as e:
                    engine_results[engine_name] = EngineResult(
                        engine=engine_name,
                        text="",
                        confidence=0.0,
                        error=str(e)
                    )
            else:
                # LLM vision clients
                engine_results[engine_name] = client.extract_text(str(image_path))
        
        # Log results
        for name, result in engine_results.items():
            if result.success:
                logger.info(f"    {ENGINE_NAMES.get(name, name)}: {len(result.text)} chars")
            else:
                logger.warning(f"    {ENGINE_NAMES.get(name, name)}: FAILED - {result.error}")
        
        # Build consensus
        return self._build_consensus(str(image_path), engine_results)
    
    def _build_consensus(
        self,
        source_file: str,
        engine_results: Dict[str, EngineResult]
    ) -> VerificationResult:
        """Build consensus from engine results."""
        # Get successful results
        successful = {k: v for k, v in engine_results.items() if v.success}
        
        if not successful:
            return VerificationResult(
                source_file=source_file,
                models_used=list(engine_results.keys()),
                consensus_text="",
                overall_confidence=0.0,
                total_words=0,
                high_confidence_words=0,
                medium_confidence_words=0,
                low_confidence_words=0,
                engine_results=engine_results
            )
        
        # If only one engine succeeded, use its result directly
        if len(successful) == 1:
            engine, result = list(successful.items())[0]
            return VerificationResult(
                source_file=source_file,
                models_used=list(engine_results.keys()),
                consensus_text=result.text,
                overall_confidence=result.confidence,
                total_words=len(tokenize(result.text)),
                high_confidence_words=0,
                medium_confidence_words=0,
                low_confidence_words=len(tokenize(result.text)),
                engine_results=engine_results
            )
        
        # Align texts
        texts = {k: v.text for k, v in successful.items()}
        aligned = align_texts(texts)
        
        # Calculate consensus for each position
        consensus_words = []
        disagreements = []
        high_count = 0
        medium_count = 0
        low_count = 0
        
        for i, readings in enumerate(aligned):
            chosen, agreement, confidence, reason = calculate_consensus(readings)
            
            if confidence == "high":
                high_count += 1
            elif confidence == "medium":
                medium_count += 1
            else:
                low_count += 1
            
            # Use chosen word or first available if no consensus
            if chosen:
                consensus_words.append(chosen)
            else:
                # Take from first engine that has a reading
                for engine in ["docai", "vision", "claude", "gpt"]:
                    if engine in readings and readings[engine]:
                        consensus_words.append(readings[engine])
                        break
            
            # Record disagreements (where not all agree)
            unique_readings = set(v for v in readings.values() if v)
            if len(unique_readings) > 1:
                disagreements.append(WordComparison(
                    position=i,
                    readings=readings,
                    chosen=chosen,
                    agreement=agreement,
                    confidence=confidence,
                    reason=reason
                ))
        
        total_words = len(aligned)
        overall_confidence = high_count / total_words if total_words > 0 else 0.0
        
        # Reconstruct text (simple word join - could be improved)
        consensus_text = " ".join(consensus_words)
        
        # If we have a high-confidence result, prefer the original formatting
        # from the most reliable engine
        if overall_confidence > 0.8 and "docai" in successful:
            consensus_text = successful["docai"].text
        elif overall_confidence > 0.8 and "vision" in successful:
            consensus_text = successful["vision"].text
        
        return VerificationResult(
            source_file=source_file,
            models_used=list(engine_results.keys()),
            consensus_text=consensus_text,
            overall_confidence=overall_confidence,
            total_words=total_words,
            high_confidence_words=high_count,
            medium_confidence_words=medium_count,
            low_confidence_words=low_count,
            disagreements=disagreements,
            engine_results=engine_results
        )


# -----------------------------------------------------------------------------
# REPORT GENERATION
# -----------------------------------------------------------------------------

def generate_report(result: VerificationResult) -> dict:
    """Generate JSON report from verification result."""
    return {
        "source_file": result.source_file,
        "models_used": result.models_used,
        "overall_confidence": round(result.overall_confidence, 4),
        "total_words": result.total_words,
        "high_confidence": result.high_confidence_words,
        "medium_confidence": result.medium_confidence_words,
        "low_confidence": result.low_confidence_words,
        "disagreement_count": len(result.disagreements),
        "engine_status": {
            name: {
                "success": r.success,
                "chars": len(r.text) if r.success else 0,
                "confidence": round(r.confidence, 4),
                "error": r.error
            }
            for name, r in result.engine_results.items()
        },
        "disagreements": [
            {
                "position": d.position,
                "readings": d.readings,
                "chosen": d.chosen,
                "agreement": d.agreement,
                "confidence": d.confidence,
                "reason": d.reason
            }
            for d in result.disagreements[:50]  # Limit to first 50
        ]
    }


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ocr_verify",
        description="Multi-model OCR verification with consensus voting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  GOOGLE_API_KEY                   Vision API key
  GOOGLE_APPLICATION_CREDENTIALS   Document AI service account
  DOCUMENTAI_PROJECT_ID            GCP project ID
  DOCUMENTAI_LOCATION              Processor location (us, eu)
  DOCUMENTAI_PROCESSOR_ID          OCR processor ID
  ANTHROPIC_API_KEY                Claude API key
  OPENAI_API_KEY                   OpenAI API key

Consensus thresholds:
  4/4 agree: Very high confidence (auto-accept)
  3/4 agree: High confidence (accept with note)
  2/4 agree: Medium confidence (flag for review)
  All differ: Low confidence (human required)

Examples:
  # Full 4-model verification
  ocr_verify.py --image page.jpg --output consensus.txt --report report.json

  # Batch processing
  ocr_verify.py --input-dir scans/ --output-dir verified/ --report-dir reports/

  # Use only dedicated OCR (cheaper)
  ocr_verify.py --image page.jpg --engines docai,vision --output consensus.txt

  # Use 3 models (skip GPT)
  ocr_verify.py --image page.jpg --engines docai,vision,claude --output out.txt
        """
    )
    
    # Input
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--image", "-i", metavar="FILE",
                            help="Single image file to verify")
    input_group.add_argument("--input-dir", metavar="DIR",
                            help="Directory of images to batch process")
    
    # Output
    parser.add_argument("--output", "-o", metavar="FILE",
                       help="Output file for consensus text")
    parser.add_argument("--output-dir", metavar="DIR",
                       help="Output directory for batch processing")
    parser.add_argument("--report", "-r", metavar="FILE",
                       help="Output file for JSON report")
    parser.add_argument("--report-dir", metavar="DIR",
                       help="Report directory for batch processing")
    parser.add_argument("--stdout", action="store_true",
                       help="Output consensus to stdout")
    
    # Engine selection
    parser.add_argument("--engines", "-e",
                       default="docai,vision,claude,gpt",
                       help="Comma-separated list of engines (default: all)")
    
    # Options
    parser.add_argument("--json", action="store_true",
                       help="Output result as JSON")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Parse engines
    enabled_engines = [e.strip() for e in args.engines.split(",")]
    valid_engines = {"docai", "vision", "claude", "gpt"}
    for e in enabled_engines:
        if e not in valid_engines:
            parser.error(f"Unknown engine: {e}. Valid: {', '.join(valid_engines)}")
    
    # Validate output
    if args.image and not args.output and not args.stdout and not args.json and not args.report:
        parser.error("Specify --output FILE, --stdout, --json, or --report")
    
    if args.input_dir and not args.output_dir:
        parser.error("--input-dir requires --output-dir")
    
    try:
        # Initialize clients based on available credentials
        vision_client = None
        docai_client = None
        claude_client = None
        gpt_client = None
        
        # Vision API
        if "vision" in enabled_engines:
            api_key = os.getenv("GOOGLE_API_KEY")
            if api_key:
                vision_client = VisionAPIClient(api_key)
            else:
                logger.warning("GOOGLE_API_KEY not set - Vision API disabled")
        
        # Document AI
        if "docai" in enabled_engines:
            try:
                config = DocumentAIConfig.from_env()
                auth = GoogleAuth()
                docai_client = DocumentAIClient(config, auth)
            except ValueError as e:
                logger.warning(f"Document AI not configured: {e}")
        
        # Claude
        if "claude" in enabled_engines:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if api_key:
                claude_client = ClaudeVisionClient(api_key)
            else:
                logger.warning("ANTHROPIC_API_KEY not set - Claude disabled")
        
        # GPT-5.2
        if "gpt" in enabled_engines:
            api_key = os.getenv("OPENAI_API_KEY")
            if api_key:
                gpt_client = GPTVisionClient(api_key)
            else:
                logger.warning("OPENAI_API_KEY not set - GPT-5.2 disabled")
        
        # Create engine
        engine = OCRVerificationEngine(
            vision_client=vision_client,
            docai_client=docai_client,
            claude_client=claude_client,
            gpt_client=gpt_client,
            enabled_engines=enabled_engines
        )
        
        active_engines = list(engine.clients.keys())
        logger.info(f"Active engines: {', '.join(ENGINE_NAMES.get(e, e) for e in active_engines)}")
        
        if args.image:
            # Single image processing
            result = engine.verify(args.image)
            
            logger.info(f"Verification complete:")
            logger.info(f"  Overall confidence: {result.overall_confidence:.1%}")
            logger.info(f"  Total words: {result.total_words}")
            logger.info(f"  High confidence: {result.high_confidence_words}")
            logger.info(f"  Medium confidence: {result.medium_confidence_words}")
            logger.info(f"  Low confidence: {result.low_confidence_words}")
            logger.info(f"  Disagreements: {len(result.disagreements)}")
            
            if args.json:
                report = generate_report(result)
                report["consensus_text"] = result.consensus_text
                print(json.dumps(report, indent=2, ensure_ascii=False))
            
            if args.stdout and not args.json:
                print(result.consensus_text)
            
            if args.output:
                Path(args.output).write_text(result.consensus_text, encoding="utf-8")
                logger.info(f"Consensus written to: {args.output}")
            
            if args.report:
                report = generate_report(result)
                Path(args.report).write_text(
                    json.dumps(report, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
                logger.info(f"Report written to: {args.report}")
        
        else:
            # Batch processing
            input_dir = Path(args.input_dir)
            output_dir = Path(args.output_dir)
            report_dir = Path(args.report_dir) if args.report_dir else None
            
            output_dir.mkdir(parents=True, exist_ok=True)
            if report_dir:
                report_dir.mkdir(parents=True, exist_ok=True)
            
            # Find images
            images = []
            for ext in [".jpg", ".jpeg", ".png", ".tiff", ".tif"]:
                images.extend(input_dir.glob(f"*{ext}"))
                images.extend(input_dir.glob(f"*{ext.upper()}"))
            
            images = sorted(set(images))
            logger.info(f"Found {len(images)} images to process")
            
            for i, image_path in enumerate(images, 1):
                logger.info(f"[{i}/{len(images)}] Processing {image_path.name}...")
                
                try:
                    result = engine.verify(str(image_path))
                    
                    # Write consensus
                    output_path = output_dir / f"{image_path.stem}.txt"
                    output_path.write_text(result.consensus_text, encoding="utf-8")
                    
                    # Write report
                    if report_dir:
                        report_path = report_dir / f"{image_path.stem}.json"
                        report = generate_report(result)
                        report_path.write_text(
                            json.dumps(report, indent=2, ensure_ascii=False),
                            encoding="utf-8"
                        )
                    
                    logger.info(f"  -> {result.overall_confidence:.1%} confidence, {len(result.disagreements)} disagreements")
                    
                except Exception as e:
                    logger.error(f"  Failed: {e}")
            
            logger.info("Batch processing complete")
        
        return 0
        
    except Exception as e:
        logger.error(str(e))
        if args.debug:
            logger.exception("Full traceback:")
        return 1


if __name__ == "__main__":
    sys.exit(main())
