#!/usr/bin/env python3
"""
Upload Omi's Letters to ResourceSpace

Creates collection resources with transcription text and links them together.
PDFs need to be uploaded manually via the UI after resources are created.

Usage:
    # Dry run (show what would be created)
    upload_omis_letters.py --dry-run

    # Create resources
    upload_omis_letters.py

Environment:
    RS_BASE_URL     ResourceSpace base URL
    RS_USER         API username (default: admin)
    RS_API_KEY      API private key (required)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("upload_omis_letters")

# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

# Base directory for Omi's letters
LETTERS_DIR = Path(__file__).parent.parent / "Omi's letters"
ORGANIZED_DIR = LETTERS_DIR / "organized"
OCR_DIR = LETTERS_DIR / "ocr"

# ResourceSpace field IDs
class FieldIDs:
    TITLE = 8
    OCR_TEXT_ORIGINAL = 88
    TRANSCRIPTION_FORMATTED = 96
    OCR_ENGINE = 90
    OCR_LANGUAGE_DETECTED = 91
    OCR_STATUS = 92

# Collection definitions
COLLECTIONS = [
    {
        "name": "complete",
        "title": "Omi's Memoir - Complete",
        "description": "Complete chronological memoir of Omi (grandmother), covering her life from Vienna before WWI, through escape from the Nazis, survival in Cairo during WWII, to building a new life in Australia.",
        "text_file": "0_complete_chronological.txt",
        "primary_pdf": None,  # No primary PDF for complete - it's a compilation
        "alt_pdfs": [],
    },
    {
        "name": "introductions",
        "title": "Omi's Memoir - 1. Introductions",
        "description": "Omi's various attempts to begin writing her memoirs for Danny. She reflects on how to structure her life story.",
        "text_file": "1_memoir_introductions.txt",
        "primary_pdf": "01_intro_dear_danny_vienna_childhood.pdf",
        "alt_pdfs": [
            "02_intro_how_to_begin.pdf",
            "03_vienna_dobling_leaving_hitler.pdf",
        ],
    },
    {
        "name": "vienna",
        "title": "Omi's Memoir - 2. Vienna Background",
        "description": "Family background and memories of Vienna after WWI. The cultural life despite poverty - theaters, opera, famous composers.",
        "text_file": "2_vienna_background.txt",
        "primary_pdf": "04_vienna_cultural_life_composers.pdf",
        "alt_pdfs": [],
    },
    {
        "name": "cairo_wwii",
        "title": "Omi's Memoir - 3. Cairo & WWII Escape",
        "description": "The most dramatic period: Life as refugees in Cairo during WWII, Vily's serious illness, the German advance at El Alamein in 1942, escape to Luxor, and the journey to Australia.",
        "text_file": "3_cairo_wwii_escape.txt",
        "primary_pdf": "05_cairo_vily_illness_heat.pdf",
        "alt_pdfs": [
            "06_1942_el_alamein_escape_luxor.pdf",
            "07_path_to_australia_mrs_lavecky.pdf",
        ],
    },
    {
        "name": "australia",
        "title": "Omi's Memoir - 4. Australia Later Years",
        "description": "Life in Australia: Karen's birth in 1977, family life, grandchildren's quotes, Blue Mountains visits.",
        "text_file": "4_australia_later_years.txt",
        "primary_pdf": "08_1977_karen_birth_family.pdf",
        "alt_pdfs": [
            "09_grandchildren_blue_mountains_diary.pdf",
            "10_blue_mountains_health_reflections.pdf",
        ],
    },
]

# -----------------------------------------------------------------------------
# API CLIENT
# -----------------------------------------------------------------------------

class ResourceSpaceClient:
    """ResourceSpace API client."""
    
    def __init__(self, base_url: str, user: str, api_key: str, timeout: int = 60):
        self.base_url = base_url.rstrip("/")
        self.user = user
        self.api_key = api_key
        self.timeout = timeout
        
        if not api_key:
            raise ValueError("RS_API_KEY is required")
    
    def _sign(self, query: str) -> str:
        return hashlib.sha256((self.api_key + query).encode()).hexdigest()
    
    def call(self, function: str, params: Dict[str, Any]) -> Any:
        """Make signed API call."""
        all_params = {"user": self.user, "function": function, **params}
        query = urllib.parse.urlencode(all_params)
        sign = self._sign(query)
        
        url = f"{self.base_url}/api/"
        post_data = urllib.parse.urlencode({
            "query": f"{query}&sign={sign}",
            "sign": sign,
            "user": self.user
        }).encode("utf-8")
        
        req = urllib.request.Request(url, data=post_data, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                if raw == "true":
                    return True
                if raw == "false":
                    return False
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code}: {body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection failed: {e.reason}")
    
    def create_resource(
        self,
        resource_type: int = 2,  # Document
        archive: int = 0
    ) -> int:
        """Create a new resource."""
        result = self.call("create_resource", {
            "resource_type": resource_type,
            "archive": archive,
        })
        
        if isinstance(result, int):
            return result
        if isinstance(result, str) and result.isdigit():
            return int(result)
        
        raise RuntimeError(f"Failed to create resource: {result}")
    
    def update_field(self, resource_id: int, field_id: int, value: str) -> bool:
        """Update a single field on a resource."""
        result = self.call("update_field", {
            "resource": resource_id,
            "field": field_id,
            "value": value
        })
        return result is True
    
    def add_related_resource(self, resource_id: int, related_id: int) -> bool:
        """Link two resources as related."""
        result = self.call("add_related_resource", {
            "resource": resource_id,
            "related": related_id
        })
        return result is True

# -----------------------------------------------------------------------------
# UPLOADER
# -----------------------------------------------------------------------------

@dataclass
class CollectionResult:
    """Result for a single collection upload."""
    name: str
    title: str
    resource_id: int = 0
    success: bool = False
    pdfs_to_upload: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

@dataclass
class UploadResult:
    """Overall upload result."""
    collections: List[CollectionResult] = field(default_factory=list)
    complete_id: int = 0
    all_linked: bool = False
    
    @property
    def success(self) -> bool:
        return all(c.success for c in self.collections) and self.all_linked

class OmisLettersUploader:
    """Uploads Omi's letters collection to ResourceSpace."""
    
    def __init__(self, client: ResourceSpaceClient, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run
    
    def upload_all(self) -> UploadResult:
        """Upload all collections."""
        result = UploadResult()
        
        # Verify directories exist
        if not LETTERS_DIR.exists():
            raise FileNotFoundError(f"Letters directory not found: {LETTERS_DIR}")
        if not ORGANIZED_DIR.exists():
            raise FileNotFoundError(f"Organized directory not found: {ORGANIZED_DIR}")
        
        logger.info(f"Uploading Omi's Letters from: {LETTERS_DIR}")
        logger.info(f"Dry run: {self.dry_run}")
        print()
        
        # Upload each collection
        for collection in COLLECTIONS:
            col_result = self._upload_collection(collection)
            result.collections.append(col_result)
            
            if collection["name"] == "complete":
                result.complete_id = col_result.resource_id
            
            print()
        
        # Link all collections to complete
        if result.complete_id and not self.dry_run:
            logger.info("Linking collections to complete memoir...")
            all_linked = True
            for col in result.collections:
                if col.name != "complete" and col.resource_id:
                    if self.client.add_related_resource(result.complete_id, col.resource_id):
                        logger.info(f"  Linked: {col.name} <-> complete")
                    else:
                        logger.error(f"  Failed to link: {col.name}")
                        all_linked = False
            result.all_linked = all_linked
        else:
            result.all_linked = True  # Nothing to link in dry run
        
        return result
    
    def _upload_collection(self, collection: dict) -> CollectionResult:
        """Upload a single collection."""
        result = CollectionResult(
            name=collection["name"],
            title=collection["title"]
        )
        
        logger.info(f"=== {collection['title']} ===")
        
        # Load transcription text
        text_file = ORGANIZED_DIR / collection["text_file"]
        if not text_file.exists():
            result.errors.append(f"Text file not found: {text_file}")
            logger.error(f"  Text file not found: {text_file}")
            return result
        
        text_content = text_file.read_text(encoding="utf-8")
        logger.info(f"  Transcription: {len(text_content):,} chars")
        
        # Collect raw OCR for this collection
        raw_ocr = self._collect_raw_ocr(collection)
        if raw_ocr:
            logger.info(f"  Raw OCR: {len(raw_ocr):,} chars")
        
        # List PDFs to upload
        pdfs = []
        if collection["primary_pdf"]:
            pdfs.append(collection["primary_pdf"])
        pdfs.extend(collection["alt_pdfs"])
        result.pdfs_to_upload = pdfs
        logger.info(f"  PDFs to upload: {len(pdfs)}")
        
        if self.dry_run:
            logger.info("  [DRY RUN] Would create resource")
            result.success = True
            result.resource_id = 0
            return result
        
        try:
            # Create resource
            logger.info("  Creating resource...")
            resource_id = self.client.create_resource(resource_type=2)
            result.resource_id = resource_id
            logger.info(f"  Created resource ID: {resource_id}")
            
            # Update title/description
            if self.client.update_field(resource_id, FieldIDs.TITLE, collection["description"]):
                logger.info("  Updated: title/description")
            
            # Update formatted transcription
            if self.client.update_field(resource_id, FieldIDs.TRANSCRIPTION_FORMATTED, text_content):
                logger.info("  Updated: formatted transcription")
            else:
                result.errors.append("Failed to update transcription field")
            
            # Update raw OCR
            if raw_ocr:
                if self.client.update_field(resource_id, FieldIDs.OCR_TEXT_ORIGINAL, raw_ocr):
                    logger.info("  Updated: raw OCR text")
            
            # Update metadata fields
            self.client.update_field(resource_id, FieldIDs.OCR_ENGINE, "Google Document AI")
            self.client.update_field(resource_id, FieldIDs.OCR_LANGUAGE_DETECTED, "en")
            self.client.update_field(resource_id, FieldIDs.OCR_STATUS, "done")
            
            result.success = True
            logger.info(f"  SUCCESS: Resource {resource_id}")
            
        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"  FAILED: {e}")
        
        return result
    
    def _collect_raw_ocr(self, collection: dict) -> str:
        """Collect raw OCR text for all PDFs in collection."""
        ocr_texts = []
        
        # Get list of PDFs
        pdfs = []
        if collection["primary_pdf"]:
            pdfs.append(collection["primary_pdf"])
        pdfs.extend(collection["alt_pdfs"])
        
        for pdf in pdfs:
            # Convert PDF name to OCR txt name
            ocr_name = pdf.replace(".pdf", ".txt")
            ocr_file = OCR_DIR / ocr_name
            if ocr_file.exists():
                ocr_texts.append(f"--- {pdf} ---\n{ocr_file.read_text(encoding='utf-8')}")
        
        return "\n\n".join(ocr_texts)

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="upload_omis_letters",
        description="Upload Omi's Letters to ResourceSpace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment:
    RS_BASE_URL     ResourceSpace URL
    RS_USER         API username (default: admin)
    RS_API_KEY      API private key (required)

This script creates 5 collection resources:
    1. Complete Memoir (all pages combined chronologically)
    2. Introductions (pages 1-3)
    3. Vienna Background (page 4)
    4. Cairo & WWII Escape (pages 5-7)
    5. Australia Later Years (pages 8-10)

After running, upload PDFs manually via ResourceSpace UI.
        """
    )
    
    parser.add_argument("--dry-run", "-n", action="store_true",
                       help="Show what would be uploaded without making changes")
    parser.add_argument("--base-url", default=os.getenv("RS_BASE_URL"),
                       help="ResourceSpace base URL")
    parser.add_argument("--user", default=os.getenv("RS_USER", "admin"),
                       help="API username")
    parser.add_argument("--api-key", default=os.getenv("RS_API_KEY"),
                       help="API private key")
    parser.add_argument("--json", action="store_true",
                       help="Output result as JSON")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    if not args.dry_run:
        if not args.api_key:
            parser.error("--api-key or RS_API_KEY required (use --dry-run to test)")
        if not args.base_url:
            parser.error("--base-url or RS_BASE_URL required")
    
    try:
        client = None
        if not args.dry_run:
            client = ResourceSpaceClient(
                base_url=args.base_url,
                user=args.user,
                api_key=args.api_key
            )
        
        uploader = OmisLettersUploader(client, dry_run=args.dry_run)
        result = uploader.upload_all()
        
        if args.json:
            output = {
                "success": result.success,
                "complete_resource_id": result.complete_id,
                "collections": [
                    {
                        "name": c.name,
                        "title": c.title,
                        "resource_id": c.resource_id,
                        "success": c.success,
                        "pdfs_to_upload": c.pdfs_to_upload,
                        "errors": c.errors
                    }
                    for c in result.collections
                ]
            }
            print(json.dumps(output, indent=2))
        else:
            print()
            print("=" * 70)
            print("UPLOAD SUMMARY")
            print("=" * 70)
            print()
            
            for c in result.collections:
                status = "OK" if c.success else "FAILED"
                rid = f"(ID: {c.resource_id})" if c.resource_id else "(dry run)"
                print(f"  [{status}] {c.title} {rid}")
                if c.pdfs_to_upload:
                    print(f"         PDFs to upload: {', '.join(c.pdfs_to_upload)}")
                if c.errors:
                    print(f"         Errors: {', '.join(c.errors)}")
            
            print()
            if result.success:
                print("All collections created successfully!")
                if not args.dry_run:
                    print()
                    print("NEXT STEPS:")
                    print("  1. Upload PDFs via ResourceSpace UI for each resource")
                    print("  2. Primary PDF -> main file upload")
                    print("  3. Additional PDFs -> 'Manage alternative files'")
                    print()
                    print("Resource URLs:")
                    for c in result.collections:
                        if c.resource_id:
                            print(f"  {c.title}: {args.base_url}/?r={c.resource_id}")
            else:
                print("Some uploads failed. Check errors above.")
        
        return 0 if result.success else 1
        
    except Exception as e:
        logger.exception("Upload failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
