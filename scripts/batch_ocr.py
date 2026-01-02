#!/usr/bin/env python3
"""
Batch OCR and Translation Pipeline

Orchestrates OCR and translation for multi-page documents with mixed languages.

Usage:
    # Process all images in a directory
    batch_ocr.py --input-dir downloads/document_123 \
        --polish-pages 1-20 --hebrew-pages 21-34

    # Dry run (show what would be processed)
    batch_ocr.py --input-dir downloads/document_123 \
        --polish-pages 1-20 --hebrew-pages 21-34 --dry-run

    # Skip OCR (if already done), only translate
    batch_ocr.py --input-dir downloads/document_123 \
        --polish-pages 1-20 --hebrew-pages 21-34 --translate-only

Environment:
    GOOGLE_API_KEY                   Google Cloud API key (Vision API)
    GOOGLE_APPLICATION_CREDENTIALS   Service account JSON (Document AI)
    DOCUMENTAI_PROJECT_ID            GCP project ID
    DOCUMENTAI_LOCATION              Processor location (us, eu)
    DOCUMENTAI_PROCESSOR_ID          OCR processor ID
    ANTHROPIC_API_KEY                Anthropic API key (for translation)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("process_batch")


# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

@dataclass
class PageRange:
    """Represents a range of pages with associated language."""
    start: int
    end: int
    language: str
    
    def __iter__(self):
        return iter(range(self.start, self.end + 1))
    
    def __contains__(self, page: int) -> bool:
        return self.start <= page <= self.end


@dataclass
class BatchConfig:
    """Configuration for batch processing."""
    input_dir: Path
    output_dir: Path
    polish_pages: Optional[PageRange] = None
    hebrew_pages: Optional[PageRange] = None
    target_language: str = "en"
    translation_model: str = "opus"
    ocr_engine: str = "auto"  # auto, vision, or documentai
    skip_ocr: bool = False
    skip_translation: bool = False
    dry_run: bool = False
    
    @classmethod
    def from_args(cls, args) -> "BatchConfig":
        input_dir = Path(args.input_dir)
        if not input_dir.exists():
            raise ValueError(f"Input directory not found: {input_dir}")
        
        output_dir = Path(args.output_dir) if args.output_dir else input_dir
        
        polish_pages = None
        if args.polish_pages:
            start, end = parse_page_range(args.polish_pages)
            polish_pages = PageRange(start, end, "pl")
        
        hebrew_pages = None
        if args.hebrew_pages:
            start, end = parse_page_range(args.hebrew_pages)
            hebrew_pages = PageRange(start, end, "he")
        
        return cls(
            input_dir=input_dir,
            output_dir=output_dir,
            polish_pages=polish_pages,
            hebrew_pages=hebrew_pages,
            target_language=args.target_language,
            translation_model=args.translation_model,
            ocr_engine=args.ocr_engine,
            skip_ocr=args.translate_only,
            skip_translation=args.ocr_only,
            dry_run=args.dry_run
        )


def parse_page_range(range_str: str) -> Tuple[int, int]:
    """Parse a page range string like '1-20' or '21-34'."""
    if "-" in range_str:
        parts = range_str.split("-")
        return int(parts[0]), int(parts[1])
    else:
        page = int(range_str)
        return page, page


# -----------------------------------------------------------------------------
# BATCH RESULT
# -----------------------------------------------------------------------------

@dataclass
class PageResult:
    """Result for a single page."""
    page_num: int
    image_file: str
    language: str
    ocr_file: Optional[str] = None
    translation_file: Optional[str] = None
    ocr_success: bool = False
    translation_success: bool = False
    ocr_chars: int = 0
    translation_chars: int = 0
    error: Optional[str] = None


@dataclass
class BatchResult:
    """Result of batch processing."""
    input_dir: str
    started: str
    completed: str = ""
    total_pages: int = 0
    ocr_success: int = 0
    ocr_failed: int = 0
    translation_success: int = 0
    translation_failed: int = 0
    pages: List[PageResult] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "input_dir": self.input_dir,
            "started": self.started,
            "completed": self.completed,
            "summary": {
                "total_pages": self.total_pages,
                "ocr_success": self.ocr_success,
                "ocr_failed": self.ocr_failed,
                "translation_success": self.translation_success,
                "translation_failed": self.translation_failed,
            },
            "pages": [
                {
                    "page": p.page_num,
                    "language": p.language,
                    "image": p.image_file,
                    "ocr": p.ocr_file,
                    "translation": p.translation_file,
                    "ocr_chars": p.ocr_chars,
                    "translation_chars": p.translation_chars,
                    "success": p.ocr_success and (p.translation_success or not p.translation_file),
                    "error": p.error
                }
                for p in self.pages
            ]
        }


# -----------------------------------------------------------------------------
# BATCH PROCESSOR
# -----------------------------------------------------------------------------

class BatchProcessor:
    """Processes a batch of document images through OCR and translation."""
    
    def __init__(self, config: BatchConfig):
        self.config = config
        self.script_dir = Path(__file__).parent
        self.ocr_script = self.script_dir / "ocr.py"  # Unified OCR with auto-detection
        self.translate_script = self.script_dir / "translate_ocr.py"
        
        # Verify scripts exist
        if not self.ocr_script.exists():
            raise FileNotFoundError(f"OCR script not found: {self.ocr_script}")
        if not self.translate_script.exists():
            raise FileNotFoundError(f"Translation script not found: {self.translate_script}")
    
    def process(self) -> BatchResult:
        """Process all pages in the batch."""
        result = BatchResult(
            input_dir=str(self.config.input_dir),
            started=datetime.now().isoformat()
        )
        
        # Find all page images
        pages = self._find_pages()
        result.total_pages = len(pages)
        
        if not pages:
            logger.warning("No page images found")
            return result
        
        logger.info(f"Found {len(pages)} pages to process")
        
        # Create output directories
        ocr_dir = self.config.output_dir / "ocr"
        trans_dir = self.config.output_dir / "translations"
        
        if not self.config.dry_run:
            ocr_dir.mkdir(parents=True, exist_ok=True)
            trans_dir.mkdir(parents=True, exist_ok=True)
        
        # Process each page
        for page_num, image_path, language in pages:
            page_result = self._process_page(
                page_num, image_path, language, ocr_dir, trans_dir
            )
            result.pages.append(page_result)
            
            if page_result.ocr_success:
                result.ocr_success += 1
            elif page_result.ocr_file:
                result.ocr_failed += 1
            
            if page_result.translation_success:
                result.translation_success += 1
            elif page_result.translation_file:
                result.translation_failed += 1
        
        result.completed = datetime.now().isoformat()
        return result
    
    def _find_pages(self) -> List[Tuple[int, Path, str]]:
        """
        Find all page images and determine their language.
        
        Returns list of (page_num, image_path, language_code).
        """
        pages = []
        
        # Look for page_XX.jpg files
        for img in sorted(self.config.input_dir.glob("page_*.jpg")):
            # Extract page number from filename
            name = img.stem  # page_01, page_02, etc.
            try:
                page_num = int(name.split("_")[1])
            except (IndexError, ValueError):
                logger.warning(f"Could not parse page number from: {img.name}")
                continue
            
            # Determine language based on page ranges
            language = self._get_language_for_page(page_num)
            if language:
                pages.append((page_num, img, language))
            else:
                logger.warning(f"Page {page_num} not in any language range, skipping")
        
        return pages
    
    def _get_language_for_page(self, page_num: int) -> Optional[str]:
        """Determine the source language for a page number."""
        if self.config.polish_pages and page_num in self.config.polish_pages:
            return "pl"
        if self.config.hebrew_pages and page_num in self.config.hebrew_pages:
            return "he"
        return None
    
    def _process_page(
        self,
        page_num: int,
        image_path: Path,
        language: str,
        ocr_dir: Path,
        trans_dir: Path
    ) -> PageResult:
        """Process a single page through OCR and translation."""
        result = PageResult(
            page_num=page_num,
            image_file=image_path.name,
            language=language
        )
        
        logger.info(f"Processing page {page_num} ({language}): {image_path.name}")
        
        if self.config.dry_run:
            result.ocr_file = f"page_{page_num:02d}_{language}.txt"
            result.translation_file = f"page_{page_num:02d}_{language}_en.txt"
            result.ocr_success = True
            result.translation_success = True
            logger.info(f"  [DRY RUN] Would process: OCR ({language}) -> Translation (en)")
            return result
        
        # OCR
        ocr_output = ocr_dir / f"page_{page_num:02d}_{language}.txt"
        result.ocr_file = ocr_output.name
        
        if not self.config.skip_ocr:
            ocr_success, ocr_chars, ocr_error = self._run_ocr(
                image_path, ocr_output, language
            )
            result.ocr_success = ocr_success
            result.ocr_chars = ocr_chars
            if ocr_error:
                result.error = f"OCR: {ocr_error}"
                return result
        else:
            # Check if OCR output exists
            if ocr_output.exists():
                result.ocr_success = True
                result.ocr_chars = len(ocr_output.read_text(encoding="utf-8"))
            else:
                result.error = f"OCR output not found: {ocr_output}"
                return result
        
        # Translation
        if not self.config.skip_translation and result.ocr_success:
            trans_output = trans_dir / f"page_{page_num:02d}_{language}_en.txt"
            result.translation_file = trans_output.name
            
            trans_success, trans_chars, trans_error = self._run_translation(
                ocr_output, trans_output, language
            )
            result.translation_success = trans_success
            result.translation_chars = trans_chars
            if trans_error:
                result.error = (result.error or "") + f" Translation: {trans_error}"
        
        return result
    
    def _run_ocr(
        self,
        image_path: Path,
        output_path: Path,
        language: str
    ) -> Tuple[bool, int, Optional[str]]:
        """
        Run OCR on an image using unified OCR script.
        
        Auto-detects handwritten vs typewritten content and routes to
        the optimal engine (Document AI for handwriting, Vision API otherwise).
        
        Returns (success, char_count, error_message).
        """
        cmd = [
            sys.executable,
            str(self.ocr_script),
            "--file", str(image_path),
            "--engine", self.config.ocr_engine,
            "--lang", language,
            "--output", str(output_path)
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env=os.environ
            )
            
            if result.returncode != 0:
                error = result.stderr.strip() if result.stderr else "Unknown error"
                logger.error(f"  OCR failed: {error}")
                return False, 0, error
            
            # Read output to get char count
            if output_path.exists():
                text = output_path.read_text(encoding="utf-8")
                logger.info(f"  OCR complete: {len(text)} chars")
                return True, len(text), None
            else:
                return False, 0, "Output file not created"
                
        except subprocess.TimeoutExpired:
            return False, 0, "OCR timeout"
        except Exception as e:
            return False, 0, str(e)
    
    def _run_translation(
        self,
        input_path: Path,
        output_path: Path,
        source_language: str
    ) -> Tuple[bool, int, Optional[str]]:
        """
        Run translation on OCR output.
        
        Returns (success, char_count, error_message).
        """
        cmd = [
            sys.executable,
            str(self.translate_script),
            "--input", str(input_path),
            "--source", source_language,
            "--target", self.config.target_language,
            "--model", self.config.translation_model,
            "--output", str(output_path)
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
                env=os.environ
            )
            
            if result.returncode != 0:
                error = result.stderr.strip() if result.stderr else "Unknown error"
                logger.error(f"  Translation failed: {error}")
                return False, 0, error
            
            # Read output to get char count
            if output_path.exists():
                text = output_path.read_text(encoding="utf-8")
                logger.info(f"  Translation complete: {len(text)} chars")
                return True, len(text), None
            else:
                return False, 0, "Output file not created"
                
        except subprocess.TimeoutExpired:
            return False, 0, "Translation timeout"
        except Exception as e:
            return False, 0, str(e)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="batch_ocr",
        description="Batch process documents through OCR and translation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  GOOGLE_API_KEY                   Vision API key (fast, typewritten)
  GOOGLE_APPLICATION_CREDENTIALS   Document AI service account (handwriting)
  DOCUMENTAI_PROJECT_ID            GCP project ID
  DOCUMENTAI_LOCATION              Processor location (us, eu)
  DOCUMENTAI_PROCESSOR_ID          OCR processor ID
  ANTHROPIC_API_KEY                Anthropic API key (Claude translation)

Examples:
  # Auto-detect handwriting and route to best OCR engine
  batch_ocr.py \\
      --input-dir downloads/document_123 \\
      --polish-pages 1-20 \\
      --hebrew-pages 21-34

  # Force Document AI for known handwritten letters
  batch_ocr.py \\
      --input-dir downloads/handwritten_letters \\
      --polish-pages 1-10 \\
      --ocr-engine documentai

  # Force Vision API for typewritten documents
  batch_ocr.py \\
      --input-dir downloads/typed_docs \\
      --polish-pages 1-20 \\
      --ocr-engine vision

  # Dry run to see what would be processed
  batch_ocr.py \\
      --input-dir downloads/document_123 \\
      --polish-pages 1-20 \\
      --hebrew-pages 21-34 \\
      --dry-run

  # Skip OCR (if already done), only translate
  batch_ocr.py \\
      --input-dir downloads/document_123 \\
      --polish-pages 1-20 \\
      --hebrew-pages 21-34 \\
      --translate-only

  # OCR only, skip translation
  batch_ocr.py \\
      --input-dir downloads/document_123 \\
      --polish-pages 1-20 \\
      --hebrew-pages 21-34 \\
      --ocr-only
        """
    )
    
    # Input/Output
    parser.add_argument("--input-dir", "-i", required=True,
                       help="Directory containing page_XX.jpg files")
    parser.add_argument("--output-dir", "-o",
                       help="Output directory (default: same as input)")
    
    # Page ranges
    parser.add_argument("--polish-pages", "-p",
                       help="Polish page range (e.g., 1-20)")
    parser.add_argument("--hebrew-pages", "-he",
                       help="Hebrew page range (e.g., 21-34)")
    
    # OCR options
    parser.add_argument("--ocr-engine", default="auto",
                       choices=["auto", "vision", "documentai"],
                       help="OCR engine: auto (detect handwriting), vision, or documentai (default: auto)")
    
    # Translation options
    parser.add_argument("--target-language", "-t", default="en",
                       help="Target language code (default: en)")
    parser.add_argument("--translation-model", default="opus",
                       choices=["opus", "sonnet", "haiku"],
                       help="Claude model for translation (default: opus)")
    
    # Processing modes
    parser.add_argument("--ocr-only", action="store_true",
                       help="Only run OCR, skip translation")
    parser.add_argument("--translate-only", action="store_true",
                       help="Only run translation (assume OCR already done)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be processed without running")
    
    # Output options
    parser.add_argument("--json", action="store_true",
                       help="Output result as JSON")
    parser.add_argument("--save-result", metavar="FILE",
                       help="Save processing result to JSON file")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate page ranges
    if not args.polish_pages and not args.hebrew_pages:
        parser.error("At least one of --polish-pages or --hebrew-pages required")
    
    try:
        config = BatchConfig.from_args(args)
        processor = BatchProcessor(config)
        
        logger.info(f"Processing: {config.input_dir}")
        logger.info(f"  OCR engine: {config.ocr_engine}")
        if config.polish_pages:
            logger.info(f"  Polish pages: {config.polish_pages.start}-{config.polish_pages.end}")
        if config.hebrew_pages:
            logger.info(f"  Hebrew pages: {config.hebrew_pages.start}-{config.hebrew_pages.end}")
        
        result = processor.process()
        
        # Output results
        if args.json:
            print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        else:
            print()
            print("=" * 60)
            print("BATCH PROCESSING COMPLETE")
            print("=" * 60)
            print(f"Total pages: {result.total_pages}")
            print(f"OCR:         {result.ocr_success} success, {result.ocr_failed} failed")
            print(f"Translation: {result.translation_success} success, {result.translation_failed} failed")
            
            # Show any errors
            errors = [p for p in result.pages if p.error]
            if errors:
                print()
                print("Errors:")
                for p in errors:
                    print(f"  Page {p.page_num}: {p.error}")
        
        if args.save_result:
            Path(args.save_result).write_text(
                json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            logger.info(f"Result saved to: {args.save_result}")
        
        # Return non-zero if any failures
        if result.ocr_failed > 0 or result.translation_failed > 0:
            return 1
        return 0
        
    except ValueError as e:
        logger.error(str(e))
        return 1
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.exception("Unexpected error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
