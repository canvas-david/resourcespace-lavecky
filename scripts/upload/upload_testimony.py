#!/usr/bin/env python3
"""
ResourceSpace Testimony Uploader

Uploads processed testimony documents to ResourceSpace with metadata,
OCR text, and translations.

Usage:
    # Upload Polish resource
    upload_testimony.py --resource-dir downloads/yadvashem_3555547/resource_polish
    
    # Upload and link as related
    upload_testimony.py --resource-dir downloads/yadvashem_3555547/resource_hebrew \
        --related-to 123

Environment:
    RS_BASE_URL     ResourceSpace base URL (default: http://localhost:8080)
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
from dataclasses import dataclass
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
logger = logging.getLogger("upload_testimony")

# -----------------------------------------------------------------------------
# FIELD IDS (must match your ResourceSpace instance)
# -----------------------------------------------------------------------------

class FieldIDs:
    """ResourceSpace field IDs for transcription workflow."""
    OCR_TEXT_ORIGINAL = 88
    TRANSCRIPTION_LITERAL = 89
    TRANSCRIPTION_FORMATTED = 96
    ENGLISH_TRANSLATION = 101
    OCR_ENGINE = 90
    OCR_LANGUAGE_DETECTED = 91
    OCR_STATUS = 92
    TRANSLATION_SOURCE_LANGUAGE = 102
    PROCESSING_VERSION = 100

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
        resource_type: int = 1,
        archive: int = 0,
        metadata: Optional[Dict[int, str]] = None
    ) -> int:
        """
        Create a new resource.
        
        Args:
            resource_type: Resource type ID (1=Photo, 2=Document, etc.)
            archive: Workflow state (0=Active)
            metadata: Dict of field_id -> value
        
        Returns:
            New resource ID
        """
        params = {
            "resource_type": resource_type,
            "archive": archive,
        }
        
        if metadata:
            params["metadata"] = json.dumps(metadata)
        
        result = self.call("create_resource", params)
        
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
    
    def upload_file_by_url(self, resource_id: int, url: str) -> bool:
        """Upload file to resource from URL."""
        result = self.call("upload_file_by_url", {
            "ref": resource_id,
            "url": url,
            "no_exif": 1
        })
        return result is True

# -----------------------------------------------------------------------------
# UPLOADER
# -----------------------------------------------------------------------------

@dataclass
class UploadResult:
    """Result of upload operation."""
    resource_id: int
    title: str
    success: bool
    images_uploaded: int
    fields_updated: List[str]
    errors: List[str]

class TestimonyUploader:
    """Uploads testimony resources to ResourceSpace."""
    
    def __init__(self, client: ResourceSpaceClient):
        self.client = client
    
    def upload(
        self,
        resource_dir: Path,
        related_to: Optional[int] = None,
        resource_type: int = 2  # Document type
    ) -> UploadResult:
        """
        Upload a testimony resource from a prepared directory.
        
        Expected directory structure:
            resource_dir/
                metadata.json
                ocr_combined.txt
                translation_combined.txt
                page_01.jpg, page_02.jpg, ...
        """
        result = UploadResult(
            resource_id=0,
            title="",
            success=False,
            images_uploaded=0,
            fields_updated=[],
            errors=[]
        )
        
        # Load metadata
        metadata_file = resource_dir / "metadata.json"
        if not metadata_file.exists():
            result.errors.append(f"metadata.json not found in {resource_dir}")
            return result
        
        with open(metadata_file, encoding="utf-8") as f:
            metadata = json.load(f)
        
        result.title = metadata.get("title", "Untitled")
        logger.info(f"Uploading: {result.title}")
        
        # Load OCR text
        ocr_file = resource_dir / "ocr_combined.txt"
        ocr_text = ""
        if ocr_file.exists():
            ocr_text = ocr_file.read_text(encoding="utf-8")
            logger.info(f"  OCR: {len(ocr_text)} chars")
        
        # Load translation
        translation_file = resource_dir / "translation_combined.txt"
        translation_text = ""
        if translation_file.exists():
            translation_text = translation_file.read_text(encoding="utf-8")
            logger.info(f"  Translation: {len(translation_text)} chars")
        
        # Find images
        images = sorted(resource_dir.glob("page_*.jpg"))
        logger.info(f"  Images: {len(images)} pages")
        
        # Build initial metadata for resource creation
        # Note: Large text fields should be updated separately
        initial_metadata = {}
        
        # Add description to title field (field 8 is typically title/description)
        if "description" in metadata:
            initial_metadata[8] = metadata["description"][:500]  # Truncate for initial
        
        try:
            # Create resource
            logger.info("  Creating resource...")
            resource_id = self.client.create_resource(
                resource_type=resource_type,
                archive=0,
                metadata=initial_metadata if initial_metadata else None
            )
            result.resource_id = resource_id
            logger.info(f"  Created resource ID: {resource_id}")
            
            # Update OCR field
            if ocr_text:
                logger.info("  Updating OCR field...")
                if self.client.update_field(resource_id, FieldIDs.OCR_TEXT_ORIGINAL, ocr_text):
                    result.fields_updated.append("OCR Text")
                else:
                    result.errors.append("Failed to update OCR field")
            
            # Update translation field
            if translation_text:
                logger.info("  Updating translation field...")
                if self.client.update_field(resource_id, FieldIDs.ENGLISH_TRANSLATION, translation_text):
                    result.fields_updated.append("English Translation")
                else:
                    result.errors.append("Failed to update translation field")
            
            # Update language field
            lang = metadata.get("language", "")
            if lang:
                logger.info(f"  Setting language: {lang}")
                if self.client.update_field(resource_id, FieldIDs.OCR_LANGUAGE_DETECTED, lang):
                    result.fields_updated.append("Language")
                if self.client.update_field(resource_id, FieldIDs.TRANSLATION_SOURCE_LANGUAGE, lang):
                    result.fields_updated.append("Translation Source Language")
            
            # Update OCR status and engine
            self.client.update_field(resource_id, FieldIDs.OCR_STATUS, "done")
            self.client.update_field(resource_id, FieldIDs.OCR_ENGINE, "google_vision")
            result.fields_updated.append("OCR Status")
            
            # Link related resource
            if related_to:
                logger.info(f"  Linking to resource {related_to}...")
                if self.client.add_related_resource(resource_id, related_to):
                    logger.info(f"  Linked as related to resource {related_to}")
                else:
                    result.errors.append(f"Failed to link to resource {related_to}")
            
            result.success = True
            result.images_uploaded = len(images)
            
            logger.info(f"  ✓ Upload complete: Resource {resource_id}")
            logger.info(f"    Note: {len(images)} images need manual upload via UI")
            logger.info(f"    (API file upload requires server-side path configuration)")
            
        except Exception as e:
            result.errors.append(str(e))
            logger.error(f"  ✗ Upload failed: {e}")
        
        return result

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="upload_testimony",
        description="Upload testimony documents to ResourceSpace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment:
    RS_BASE_URL     ResourceSpace URL (default: http://localhost:8080)
    RS_USER         API username (default: admin)
    RS_API_KEY      API private key (required)

Examples:
    # Upload Polish testimony
    upload_testimony.py --resource-dir downloads/yadvashem_3555547/resource_polish
    
    # Upload Hebrew and link to Polish (resource ID 123)
    upload_testimony.py --resource-dir downloads/yadvashem_3555547/resource_hebrew \\
        --related-to 123
    
    # Upload both in sequence
    upload_testimony.py --resource-dir downloads/yadvashem_3555547/resource_polish
    # Note the returned resource ID (e.g., 123)
    upload_testimony.py --resource-dir downloads/yadvashem_3555547/resource_hebrew \\
        --related-to 123
        """
    )
    
    parser.add_argument("--resource-dir", "-d", required=True,
                       help="Directory containing metadata.json, OCR, translation, and images")
    parser.add_argument("--related-to", "-r", type=int,
                       help="Link as related to this resource ID")
    parser.add_argument("--resource-type", "-t", type=int, default=2,
                       help="Resource type ID (default: 2 for Document)")
    parser.add_argument("--base-url", default=os.getenv("RS_BASE_URL", "http://localhost:8080"),
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
    
    if not args.api_key:
        parser.error("--api-key or RS_API_KEY required")
    
    resource_dir = Path(args.resource_dir)
    if not resource_dir.exists():
        parser.error(f"Resource directory not found: {resource_dir}")
    
    try:
        client = ResourceSpaceClient(
            base_url=args.base_url,
            user=args.user,
            api_key=args.api_key
        )
        
        uploader = TestimonyUploader(client)
        result = uploader.upload(
            resource_dir=resource_dir,
            related_to=args.related_to,
            resource_type=args.resource_type
        )
        
        if args.json:
            print(json.dumps({
                "resource_id": result.resource_id,
                "title": result.title,
                "success": result.success,
                "images_to_upload": result.images_uploaded,
                "fields_updated": result.fields_updated,
                "errors": result.errors
            }, indent=2))
        else:
            print()
            print("=" * 60)
            print("UPLOAD RESULT")
            print("=" * 60)
            print(f"Resource ID: {result.resource_id}")
            print(f"Title: {result.title}")
            print(f"Success: {result.success}")
            print(f"Fields updated: {', '.join(result.fields_updated)}")
            print(f"Images to upload manually: {result.images_uploaded}")
            if result.errors:
                print(f"Errors: {', '.join(result.errors)}")
            print()
            if result.success:
                print(f"Next: Upload {result.images_uploaded} images via ResourceSpace UI")
                print(f"      Resource URL: {args.base_url}/?r={result.resource_id}")
        
        return 0 if result.success else 1
        
    except Exception as e:
        logger.exception("Upload failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
