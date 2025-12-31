#!/usr/bin/env python3
"""
ResourceSpace Transcription Sync

Syncs OCR and transcription layers to ResourceSpace following archival rules:
- OCR Text (Original): IMMUTABLE once set
- Transcription (Cleaned – Literal): Write-once by default, --force-literal to update
- Transcription (Reader Formatted): Iterable, updates when content changes

Usage:
    sync_transcription --resource-id 123 --ocr ocr.txt --literal literal.txt \
        --formatted formatted.txt --lang de --version v1.2.0

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
from dataclasses import dataclass, field as dataclass_field
from enum import Enum
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
logger = logging.getLogger("sync_transcription")


# -----------------------------------------------------------------------------
# FIELD CONFIGURATION
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldIDs:
    """
    ResourceSpace field IDs.
    
    These MUST match your ResourceSpace instance.
    Run with --list-fields to verify.
    """
    # Primary content fields
    OCR_TEXT_ORIGINAL: int = 88              # Immutable
    TRANSCRIPTION_LITERAL: int = 89          # Write-once default
    TRANSCRIPTION_FORMATTED: int = 96        # Iterable
    
    # OCR metadata
    OCR_ENGINE: int = 90
    OCR_LANGUAGE_DETECTED: int = 91
    OCR_STATUS: int = 92
    
    # Literal transcription metadata
    TRANSCRIPTION_METHOD: int = 93
    TRANSCRIPTION_REVIEW_STATUS: int = 94
    TRANSCRIPTION_NOTES: int = 95
    
    # Formatted transcription metadata
    FORMATTING_METHOD: int = 97
    FORMATTING_REVIEW_STATUS: int = 98
    FORMATTING_NOTES: int = 99
    
    # Audit
    PROCESSING_VERSION: int = 100


FIELDS = FieldIDs()


# -----------------------------------------------------------------------------
# ENUMS
# -----------------------------------------------------------------------------

class OCREngine(Enum):
    GOOGLE_DOCUMENT_AI = "google_document_ai"
    GOOGLE_VISION = "google_vision"
    TESSERACT = "tesseract"


class OCRStatus(Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class TranscriptionMethod(Enum):
    AI_SPELLING_NORMALISATION_ONLY = "ai_spelling_normalisation_only"
    MANUAL = "manual"


class ReviewStatus(Enum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    APPROVED = "approved"


class FormattingMethod(Enum):
    AI_FORMATTING_ONLY_NON_EDITORIAL = "ai_formatting_only_non_editorial"
    MANUAL = "manual"


# -----------------------------------------------------------------------------
# EXCEPTIONS
# -----------------------------------------------------------------------------

class SyncError(Exception):
    """Base exception."""
    pass


class ImmutableFieldError(SyncError):
    """Raised when attempting to overwrite immutable field."""
    pass


class WriteOnceFieldError(SyncError):
    """Raised when attempting to overwrite write-once field without force."""
    pass


class ResourceNotFoundError(SyncError):
    """Raised when resource doesn't exist."""
    pass


class AuthenticationError(SyncError):
    """Raised on API auth failure."""
    pass


class APIError(SyncError):
    """Raised on general API errors."""
    pass


class FieldNotFoundError(SyncError):
    """Raised when field ID doesn't exist."""
    pass


# -----------------------------------------------------------------------------
# SYNC RESULT
# -----------------------------------------------------------------------------

@dataclass
class FieldChange:
    """Record of a single field change."""
    field_id: int
    field_name: str
    action: str  # "created", "updated", "skipped", "unchanged"
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class SyncResult:
    """Result of a sync operation."""
    resource_id: int
    success: bool
    changes: List[FieldChange] = dataclass_field(default_factory=list)
    errors: List[str] = dataclass_field(default_factory=list)
    version: Optional[str] = None
    
    def add_change(self, change: FieldChange) -> None:
        self.changes.append(change)
        action_emoji = {
            "created": "✓",
            "updated": "↻",
            "skipped": "⊘",
            "unchanged": "="
        }
        emoji = action_emoji.get(change.action, "?")
        logger.info(f"  {emoji} {change.field_name}: {change.action}" + 
                   (f" ({change.reason})" if change.reason else ""))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "success": self.success,
            "version": self.version,
            "changes": [
                {
                    "field_id": c.field_id,
                    "field_name": c.field_name,
                    "action": c.action,
                    "reason": c.reason
                }
                for c in self.changes
            ],
            "errors": self.errors
        }


# -----------------------------------------------------------------------------
# API CLIENT
# -----------------------------------------------------------------------------

class ResourceSpaceClient:
    """Low-level ResourceSpace API client."""
    
    def __init__(
        self,
        base_url: str,
        user: str,
        api_key: str,
        timeout: int = 30
    ):
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
            if e.code == 401 or "authentication" in body.lower():
                raise AuthenticationError(f"Auth failed: {body}")
            raise APIError(f"HTTP {e.code}: {body}")
        except urllib.error.URLError as e:
            raise APIError(f"Connection failed: {e.reason}")


# -----------------------------------------------------------------------------
# TRANSCRIPTION SYNC
# -----------------------------------------------------------------------------

class TranscriptionSync:
    """
    Syncs OCR and transcription data to ResourceSpace.
    
    Write rules:
    - OCR Text (Original): IMMUTABLE - never overwrite
    - Transcription (Cleaned – Literal): Write-once, force flag to update
    - Transcription (Reader Formatted): Iterable, update when changed
    """
    
    def __init__(
        self,
        client: ResourceSpaceClient,
        fields: FieldIDs = FIELDS
    ):
        self.client = client
        self.fields = fields
        self._field_cache: Dict[int, Dict[str, Any]] = {}
    
    # -------------------------------------------------------------------------
    # Field operations
    # -------------------------------------------------------------------------
    
    def get_resource_fields(self, resource_id: int) -> Dict[int, str]:
        """
        Get all field values for a resource.
        
        Returns:
            Dict mapping field_id -> value (empty string if unset)
        """
        # Verify resource exists
        res = self.client.call("get_resource_data", {"resource": resource_id})
        if not res or (isinstance(res, dict) and res.get("error")):
            raise ResourceNotFoundError(f"Resource {resource_id} not found")
        
        # Get field data
        fields = self.client.call("get_resource_field_data", {"resource": resource_id})
        if not isinstance(fields, list):
            raise APIError(f"Unexpected response: {fields}")
        
        result = {}
        for f in fields:
            fid = f.get("ref") or f.get("fref")
            if fid:
                result[fid] = f.get("value", "") or ""
        
        return result
    
    def get_field_value(self, resource_id: int, field_id: int) -> Optional[str]:
        """Get single field value, None if empty."""
        fields = self.get_resource_fields(resource_id)
        value = fields.get(field_id, "")
        return value if value.strip() else None
    
    def update_field(self, resource_id: int, field_id: int, value: str) -> bool:
        """Update single field."""
        result = self.client.call("update_field", {
            "resource": resource_id,
            "field": field_id,
            "value": value
        })
        if result is not True:
            raise APIError(f"Failed to update field {field_id}: {result}")
        return True
    
    def is_empty(self, value: Optional[str]) -> bool:
        """Check if value is empty/None."""
        return value is None or value.strip() == ""
    
    def values_equal(self, a: Optional[str], b: Optional[str]) -> bool:
        """Compare two values, treating empty/None as equivalent."""
        a_norm = (a or "").strip()
        b_norm = (b or "").strip()
        return a_norm == b_norm
    
    # -------------------------------------------------------------------------
    # Sync operations
    # -------------------------------------------------------------------------
    
    def sync(
        self,
        resource_id: int,
        ocr_text: Optional[str] = None,
        literal_text: Optional[str] = None,
        formatted_text: Optional[str] = None,
        language: Optional[str] = None,
        version: Optional[str] = None,
        force_literal: bool = False
    ) -> SyncResult:
        """
        Sync all transcription layers to ResourceSpace.
        
        Args:
            resource_id: Target resource
            ocr_text: Raw OCR output (write-once, immutable)
            literal_text: Cleaned literal transcription (write-once default)
            formatted_text: Reader formatted transcription (iterable)
            language: Detected language code
            version: Pipeline version string
            force_literal: Allow overwriting literal transcription
        
        Returns:
            SyncResult with all changes made
        """
        result = SyncResult(resource_id=resource_id, success=True, version=version)
        
        logger.info(f"Syncing resource {resource_id}")
        
        try:
            # Fetch current state
            current = self.get_resource_fields(resource_id)
            
            # Sync each layer
            if ocr_text is not None:
                self._sync_ocr(resource_id, ocr_text, language, current, result)
            
            if literal_text is not None:
                self._sync_literal(resource_id, literal_text, force_literal, current, result)
            
            if formatted_text is not None:
                self._sync_formatted(resource_id, formatted_text, current, result)
            
            # Always write version on successful sync
            if version:
                self._write_version(resource_id, version, current, result)
            
        except SyncError as e:
            result.success = False
            result.errors.append(str(e))
            logger.error(f"Sync failed: {e}")
        except Exception as e:
            result.success = False
            result.errors.append(f"Unexpected error: {e}")
            logger.exception("Unexpected error during sync")
        
        return result
    
    def _sync_ocr(
        self,
        resource_id: int,
        ocr_text: str,
        language: Optional[str],
        current: Dict[int, str],
        result: SyncResult
    ) -> None:
        """
        Sync OCR layer (IMMUTABLE).
        
        Rule: Never overwrite once set.
        """
        existing = current.get(self.fields.OCR_TEXT_ORIGINAL, "")
        
        if not self.is_empty(existing):
            # Field is populated - NEVER overwrite
            result.add_change(FieldChange(
                field_id=self.fields.OCR_TEXT_ORIGINAL,
                field_name="OCR Text (Original)",
                action="skipped",
                reason=f"immutable, already set ({len(existing)} chars)"
            ))
            return
        
        # Write OCR text
        self.update_field(resource_id, self.fields.OCR_TEXT_ORIGINAL, ocr_text)
        result.add_change(FieldChange(
            field_id=self.fields.OCR_TEXT_ORIGINAL,
            field_name="OCR Text (Original)",
            action="created",
            new_value=f"{len(ocr_text)} chars"
        ))
        
        # Write OCR metadata
        self.update_field(resource_id, self.fields.OCR_ENGINE, 
                         OCREngine.GOOGLE_DOCUMENT_AI.value)
        result.add_change(FieldChange(
            field_id=self.fields.OCR_ENGINE,
            field_name="ocr_engine",
            action="created",
            new_value=OCREngine.GOOGLE_DOCUMENT_AI.value
        ))
        
        self.update_field(resource_id, self.fields.OCR_STATUS, OCRStatus.DONE.value)
        result.add_change(FieldChange(
            field_id=self.fields.OCR_STATUS,
            field_name="ocr_status",
            action="created",
            new_value=OCRStatus.DONE.value
        ))
        
        if language:
            self.update_field(resource_id, self.fields.OCR_LANGUAGE_DETECTED, language)
            result.add_change(FieldChange(
                field_id=self.fields.OCR_LANGUAGE_DETECTED,
                field_name="ocr_language_detected",
                action="created",
                new_value=language
            ))
    
    def _sync_literal(
        self,
        resource_id: int,
        literal_text: str,
        force: bool,
        current: Dict[int, str],
        result: SyncResult
    ) -> None:
        """
        Sync literal transcription layer (write-once default).
        
        Rule: Write once unless --force-literal is passed.
        """
        existing = current.get(self.fields.TRANSCRIPTION_LITERAL, "")
        
        if not self.is_empty(existing) and not force:
            # Field is populated and no force flag
            result.add_change(FieldChange(
                field_id=self.fields.TRANSCRIPTION_LITERAL,
                field_name="Transcription (Cleaned – Literal)",
                action="skipped",
                reason=f"write-once, already set ({len(existing)} chars), use --force-literal to update"
            ))
            return
        
        if self.values_equal(existing, literal_text):
            result.add_change(FieldChange(
                field_id=self.fields.TRANSCRIPTION_LITERAL,
                field_name="Transcription (Cleaned – Literal)",
                action="unchanged",
                reason="content identical"
            ))
            return
        
        action = "updated" if not self.is_empty(existing) else "created"
        
        # Write transcription
        self.update_field(resource_id, self.fields.TRANSCRIPTION_LITERAL, literal_text)
        result.add_change(FieldChange(
            field_id=self.fields.TRANSCRIPTION_LITERAL,
            field_name="Transcription (Cleaned – Literal)",
            action=action,
            new_value=f"{len(literal_text)} chars"
        ))
        
        # Write metadata
        self.update_field(resource_id, self.fields.TRANSCRIPTION_METHOD,
                         TranscriptionMethod.AI_SPELLING_NORMALISATION_ONLY.value)
        result.add_change(FieldChange(
            field_id=self.fields.TRANSCRIPTION_METHOD,
            field_name="transcription_method",
            action=action,
            new_value=TranscriptionMethod.AI_SPELLING_NORMALISATION_ONLY.value
        ))
        
        self.update_field(resource_id, self.fields.TRANSCRIPTION_REVIEW_STATUS,
                         ReviewStatus.REVIEWED.value)
        result.add_change(FieldChange(
            field_id=self.fields.TRANSCRIPTION_REVIEW_STATUS,
            field_name="transcription_review_status",
            action=action,
            new_value=ReviewStatus.REVIEWED.value
        ))
        
        notes = "spelling normalised only; tone and wording preserved"
        self.update_field(resource_id, self.fields.TRANSCRIPTION_NOTES, notes)
        result.add_change(FieldChange(
            field_id=self.fields.TRANSCRIPTION_NOTES,
            field_name="transcription_notes",
            action=action,
            new_value=notes
        ))
    
    def _sync_formatted(
        self,
        resource_id: int,
        formatted_text: str,
        current: Dict[int, str],
        result: SyncResult
    ) -> None:
        """
        Sync reader formatted transcription layer (iterable).
        
        Rule: Update when content changes. Never downgrade review status.
        """
        existing = current.get(self.fields.TRANSCRIPTION_FORMATTED, "")
        
        if self.values_equal(existing, formatted_text):
            result.add_change(FieldChange(
                field_id=self.fields.TRANSCRIPTION_FORMATTED,
                field_name="Transcription (Reader Formatted)",
                action="unchanged",
                reason="content identical"
            ))
            return
        
        action = "updated" if not self.is_empty(existing) else "created"
        
        # Write formatted text
        self.update_field(resource_id, self.fields.TRANSCRIPTION_FORMATTED, formatted_text)
        result.add_change(FieldChange(
            field_id=self.fields.TRANSCRIPTION_FORMATTED,
            field_name="Transcription (Reader Formatted)",
            action=action,
            new_value=f"{len(formatted_text)} chars"
        ))
        
        # Write formatting metadata
        self.update_field(resource_id, self.fields.FORMATTING_METHOD,
                         FormattingMethod.AI_FORMATTING_ONLY_NON_EDITORIAL.value)
        result.add_change(FieldChange(
            field_id=self.fields.FORMATTING_METHOD,
            field_name="formatting_method",
            action=action,
            new_value=FormattingMethod.AI_FORMATTING_ONLY_NON_EDITORIAL.value
        ))
        
        # Review status: set to unreviewed ONLY if not already reviewed/approved
        # (never downgrade)
        existing_review = current.get(self.fields.FORMATTING_REVIEW_STATUS, "")
        keep_statuses = [ReviewStatus.REVIEWED.value, ReviewStatus.APPROVED.value]
        
        if existing_review not in keep_statuses:
            self.update_field(resource_id, self.fields.FORMATTING_REVIEW_STATUS,
                             ReviewStatus.UNREVIEWED.value)
            result.add_change(FieldChange(
                field_id=self.fields.FORMATTING_REVIEW_STATUS,
                field_name="formatting_review_status",
                action=action,
                new_value=ReviewStatus.UNREVIEWED.value
            ))
        else:
            result.add_change(FieldChange(
                field_id=self.fields.FORMATTING_REVIEW_STATUS,
                field_name="formatting_review_status",
                action="unchanged",
                reason=f"kept existing '{existing_review}' (no downgrade)"
            ))
        
        # Notes
        notes = "paragraphing/punctuation/headers only; no rewriting"
        self.update_field(resource_id, self.fields.FORMATTING_NOTES, notes)
        result.add_change(FieldChange(
            field_id=self.fields.FORMATTING_NOTES,
            field_name="formatting_notes",
            action=action,
            new_value=notes
        ))
    
    def _write_version(
        self,
        resource_id: int,
        version: str,
        current: Dict[int, str],
        result: SyncResult
    ) -> None:
        """Write processing version."""
        existing = current.get(self.fields.PROCESSING_VERSION, "")
        
        if existing == version:
            result.add_change(FieldChange(
                field_id=self.fields.PROCESSING_VERSION,
                field_name="processing_version",
                action="unchanged",
                reason="same version"
            ))
            return
        
        action = "updated" if not self.is_empty(existing) else "created"
        self.update_field(resource_id, self.fields.PROCESSING_VERSION, version)
        result.add_change(FieldChange(
            field_id=self.fields.PROCESSING_VERSION,
            field_name="processing_version",
            action=action,
            old_value=existing if existing else None,
            new_value=version
        ))
    
    # -------------------------------------------------------------------------
    # Status query
    # -------------------------------------------------------------------------
    
    def get_status(self, resource_id: int) -> Dict[str, Any]:
        """Get full transcription status for a resource."""
        current = self.get_resource_fields(resource_id)
        
        def get_val(fid: int) -> Optional[str]:
            v = current.get(fid, "")
            return v if v.strip() else None
        
        def get_len(fid: int) -> int:
            v = current.get(fid, "")
            return len(v) if v.strip() else 0
        
        return {
            "resource_id": resource_id,
            "ocr": {
                "populated": get_len(self.fields.OCR_TEXT_ORIGINAL) > 0,
                "chars": get_len(self.fields.OCR_TEXT_ORIGINAL),
                "engine": get_val(self.fields.OCR_ENGINE),
                "language": get_val(self.fields.OCR_LANGUAGE_DETECTED),
                "status": get_val(self.fields.OCR_STATUS),
            },
            "literal": {
                "populated": get_len(self.fields.TRANSCRIPTION_LITERAL) > 0,
                "chars": get_len(self.fields.TRANSCRIPTION_LITERAL),
                "method": get_val(self.fields.TRANSCRIPTION_METHOD),
                "review_status": get_val(self.fields.TRANSCRIPTION_REVIEW_STATUS),
                "notes": get_val(self.fields.TRANSCRIPTION_NOTES),
            },
            "formatted": {
                "populated": get_len(self.fields.TRANSCRIPTION_FORMATTED) > 0,
                "chars": get_len(self.fields.TRANSCRIPTION_FORMATTED),
                "method": get_val(self.fields.FORMATTING_METHOD),
                "review_status": get_val(self.fields.FORMATTING_REVIEW_STATUS),
                "notes": get_val(self.fields.FORMATTING_NOTES),
            },
            "processing_version": get_val(self.fields.PROCESSING_VERSION),
        }


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def read_file(path: str) -> str:
    """Read text file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {path}")
    return p.read_text(encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sync_transcription",
        description="Sync OCR and transcription data to ResourceSpace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  RS_BASE_URL     ResourceSpace URL (default: http://localhost:8080)
  RS_USER         API username (default: admin)
  RS_API_KEY      API private key (required)

Examples:
  # Full sync
  sync_transcription --resource-id 123 --ocr ocr.txt --literal literal.txt \\
      --formatted formatted.txt --lang de --version v1.2.0
  
  # OCR only
  sync_transcription --resource-id 123 --ocr ocr.txt --lang en
  
  # Update formatted only (iterable)
  sync_transcription --resource-id 123 --formatted formatted_v2.txt --version v1.3.0
  
  # Force literal update
  sync_transcription --resource-id 123 --literal corrected.txt --force-literal
  
  # Check status
  sync_transcription --resource-id 123 --status
  
  # List field IDs
  sync_transcription --list-fields
        """
    )
    
    # Connection
    parser.add_argument("--url", default=os.getenv("RS_BASE_URL", "http://localhost:8080"),
                       help="ResourceSpace URL")
    parser.add_argument("--user", default=os.getenv("RS_USER", "admin"),
                       help="API user")
    parser.add_argument("--key", default=os.getenv("RS_API_KEY"),
                       help="API key (or RS_API_KEY env var)")
    
    # Target
    parser.add_argument("--resource-id", type=int, help="Resource ID")
    
    # Content files
    parser.add_argument("--ocr", metavar="FILE", help="OCR text file (write-once, immutable)")
    parser.add_argument("--literal", metavar="FILE", help="Literal transcription file (write-once default)")
    parser.add_argument("--formatted", metavar="FILE", help="Reader formatted file (iterable)")
    
    # Metadata
    parser.add_argument("--lang", help="Detected language code (e.g., en, de, he)")
    parser.add_argument("--version", help="Pipeline version (e.g., v1.2.0)")
    
    # Flags
    parser.add_argument("--force-literal", action="store_true",
                       help="Allow overwriting literal transcription")
    
    # Actions
    parser.add_argument("--status", action="store_true", help="Show current status")
    parser.add_argument("--list-fields", action="store_true", help="List field IDs")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    args = parser.parse_args()
    
    # Validate API key
    if not args.key and not args.list_fields:
        parser.error("--key or RS_API_KEY environment variable required")
    
    # List fields action
    if args.list_fields:
        if not args.key:
            parser.error("--key required for --list-fields")
        client = ResourceSpaceClient(args.url, args.user, args.key)
        fields = client.call("get_resource_type_fields", {"resource_type": 2})
        print(f"\n{'ID':>4}  {'Name':<40}  Title")
        print("-" * 80)
        for f in sorted(fields, key=lambda x: x["ref"]):
            print(f"{f['ref']:>4}  {f['name']:<40}  {f['title']}")
        return 0
    
    # Require resource ID for other actions
    if not args.resource_id:
        parser.error("--resource-id required")
    
    # Create sync client
    client = ResourceSpaceClient(args.url, args.user, args.key)
    sync = TranscriptionSync(client)
    
    # Status action
    if args.status:
        try:
            status = sync.get_status(args.resource_id)
            if args.json:
                print(json.dumps(status, indent=2))
            else:
                print(f"\nResource {args.resource_id} Status")
                print("=" * 50)
                print(f"Processing Version: {status['processing_version'] or '(not set)'}")
                print()
                for layer in ["ocr", "literal", "formatted"]:
                    data = status[layer]
                    print(f"{layer.upper()}:")
                    print(f"  Populated: {data['populated']} ({data['chars']} chars)")
                    for k, v in data.items():
                        if k not in ["populated", "chars"]:
                            print(f"  {k}: {v or '(not set)'}")
                    print()
            return 0
        except SyncError as e:
            logger.error(str(e))
            return 1
    
    # Sync action
    if not any([args.ocr, args.literal, args.formatted]):
        parser.error("At least one of --ocr, --literal, or --formatted required")
    
    try:
        # Read files
        ocr_text = read_file(args.ocr) if args.ocr else None
        literal_text = read_file(args.literal) if args.literal else None
        formatted_text = read_file(args.formatted) if args.formatted else None
        
        # Execute sync
        result = sync.sync(
            resource_id=args.resource_id,
            ocr_text=ocr_text,
            literal_text=literal_text,
            formatted_text=formatted_text,
            language=args.lang,
            version=args.version,
            force_literal=args.force_literal
        )
        
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print()
            print("=" * 50)
            if result.success:
                created = sum(1 for c in result.changes if c.action == "created")
                updated = sum(1 for c in result.changes if c.action == "updated")
                skipped = sum(1 for c in result.changes if c.action == "skipped")
                unchanged = sum(1 for c in result.changes if c.action == "unchanged")
                print(f"✓ Sync complete: {created} created, {updated} updated, "
                      f"{skipped} skipped, {unchanged} unchanged")
            else:
                print(f"✗ Sync failed: {', '.join(result.errors)}")
        
        return 0 if result.success else 1
        
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1
    except SyncError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.exception("Unexpected error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
