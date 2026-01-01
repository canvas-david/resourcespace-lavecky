#!/usr/bin/env python3
"""
Google Document AI OCR Processor

Processes documents through Google Cloud Document AI and syncs results to ResourceSpace.

Usage:
    # Process and sync to ResourceSpace
    process_ocr.py --file document.pdf --resource-id 123

    # Process only (output OCR text)
    process_ocr.py --file document.pdf --output ocr.txt

    # Process with language hint
    process_ocr.py --file document.pdf --resource-id 123 --lang de

Environment:
    GOOGLE_APPLICATION_CREDENTIALS   Path to service account JSON key
    DOCUMENTAI_PROJECT_ID            GCP project ID
    DOCUMENTAI_LOCATION              Processor location (us, eu)
    DOCUMENTAI_PROCESSOR_ID          OCR processor ID
    
    # For ResourceSpace sync (optional)
    RS_BASE_URL                      ResourceSpace URL
    RS_USER                          API username
    RS_API_KEY                       API private key
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("process_ocr")


# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

@dataclass
class DocumentAIConfig:
    """Document AI configuration from environment."""
    project_id: str
    location: str
    processor_id: str
    
    @classmethod
    def from_env(cls) -> "DocumentAIConfig":
        project_id = os.getenv("DOCUMENTAI_PROJECT_ID")
        location = os.getenv("DOCUMENTAI_LOCATION", "us")
        processor_id = os.getenv("DOCUMENTAI_PROCESSOR_ID")
        
        if not project_id:
            raise ValueError("DOCUMENTAI_PROJECT_ID environment variable required")
        if not processor_id:
            raise ValueError("DOCUMENTAI_PROCESSOR_ID environment variable required")
        
        return cls(
            project_id=project_id,
            location=location,
            processor_id=processor_id
        )
    
    @property
    def endpoint(self) -> str:
        """Document AI API endpoint."""
        return f"https://{self.location}-documentai.googleapis.com"
    
    @property
    def processor_name(self) -> str:
        """Full processor resource name."""
        return (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/processors/{self.processor_id}"
        )


# -----------------------------------------------------------------------------
# GOOGLE AUTH
# -----------------------------------------------------------------------------

class GoogleAuth:
    """
    Handles Google Cloud authentication using service account.
    
    Uses the GOOGLE_APPLICATION_CREDENTIALS environment variable
    to locate the service account JSON key file.
    """
    
    def __init__(self):
        self._token: Optional[str] = None
        self._token_expiry: float = 0
    
    def get_access_token(self) -> str:
        """
        Get a valid access token, refreshing if necessary.
        
        Uses the metadata server in GCP environments, otherwise
        exchanges the service account key for an access token.
        """
        import time
        
        # Return cached token if still valid (with 60s buffer)
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        
        # Try metadata server first (for GCP environments)
        try:
            token, expiry = self._get_token_from_metadata()
            self._token = token
            self._token_expiry = expiry
            return self._token
        except Exception:
            pass
        
        # Fall back to service account key
        token, expiry = self._get_token_from_service_account()
        self._token = token
        self._token_expiry = expiry
        return self._token
    
    def _get_token_from_metadata(self) -> Tuple[str, float]:
        """Get token from GCP metadata server."""
        import time
        
        url = (
            "http://metadata.google.internal/computeMetadata/v1/"
            "instance/service-accounts/default/token"
        )
        req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
        
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            return data["access_token"], time.time() + data["expires_in"]
    
    def _get_token_from_service_account(self) -> Tuple[str, float]:
        """Exchange service account key for access token."""
        import time
        import hashlib
        import hmac
        
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            raise ValueError(
                "GOOGLE_APPLICATION_CREDENTIALS environment variable required"
            )
        
        with open(creds_path) as f:
            creds = json.load(f)
        
        # Build JWT
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        payload = {
            "iss": creds["client_email"],
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600
        }
        
        # Encode JWT parts
        def b64_encode(data: dict) -> str:
            return base64.urlsafe_b64encode(
                json.dumps(data, separators=(",", ":")).encode()
            ).rstrip(b"=").decode()
        
        header_b64 = b64_encode(header)
        payload_b64 = b64_encode(payload)
        signing_input = f"{header_b64}.{payload_b64}"
        
        # Sign with RSA
        signature = self._sign_rs256(signing_input, creds["private_key"])
        jwt = f"{signing_input}.{signature}"
        
        # Exchange JWT for access token
        token_url = "https://oauth2.googleapis.com/token"
        post_data = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": jwt
        }).encode()
        
        req = urllib.request.Request(token_url, data=post_data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data["access_token"], time.time() + data.get("expires_in", 3600)
    
    def _sign_rs256(self, message: str, private_key_pem: str) -> str:
        """Sign message with RS256 (RSA + SHA256)."""
        try:
            # Try cryptography library first
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            
            private_key = serialization.load_pem_private_key(
                private_key_pem.encode(),
                password=None
            )
            signature = private_key.sign(
                message.encode(),
                padding.PKCS1v15(),
                hashes.SHA256()
            )
            return base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        except ImportError:
            pass
        
        # Fall back to subprocess with openssl
        import subprocess
        import tempfile
        
        with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
            f.write(private_key_pem)
            key_file = f.name
        
        try:
            result = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", key_file],
                input=message.encode(),
                capture_output=True,
                check=True
            )
            return base64.urlsafe_b64encode(result.stdout).rstrip(b"=").decode()
        finally:
            os.unlink(key_file)


# Need urllib.parse for token exchange
import urllib.parse


# -----------------------------------------------------------------------------
# DOCUMENT AI CLIENT
# -----------------------------------------------------------------------------

@dataclass
class OCRResult:
    """Result from Document AI OCR processing."""
    text: str
    confidence: float
    language_codes: List[str]
    page_count: int
    
    def detected_language(self) -> Optional[str]:
        """Return primary detected language code."""
        return self.language_codes[0] if self.language_codes else None


class DocumentAIClient:
    """Client for Google Cloud Document AI."""
    
    # Maximum file size for inline processing (20MB)
    MAX_INLINE_SIZE = 20 * 1024 * 1024
    
    # Supported MIME types
    SUPPORTED_TYPES = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".gif": "image/gif",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }
    
    def __init__(self, config: DocumentAIConfig, auth: GoogleAuth):
        self.config = config
        self.auth = auth
    
    def process_document(
        self,
        file_path: str,
        language_hints: Optional[List[str]] = None
    ) -> OCRResult:
        """
        Process a document through Document AI OCR.
        
        Args:
            file_path: Path to document (PDF or image)
            language_hints: Optional language codes to improve OCR accuracy
        
        Returns:
            OCRResult with extracted text and metadata
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        # Determine MIME type
        suffix = path.suffix.lower()
        mime_type = self.SUPPORTED_TYPES.get(suffix)
        if not mime_type:
            raise ValueError(
                f"Unsupported file type: {suffix}. "
                f"Supported: {', '.join(self.SUPPORTED_TYPES.keys())}"
            )
        
        # Check file size
        file_size = path.stat().st_size
        if file_size > self.MAX_INLINE_SIZE:
            raise ValueError(
                f"File too large for inline processing: {file_size / 1024 / 1024:.1f}MB. "
                f"Maximum: {self.MAX_INLINE_SIZE / 1024 / 1024:.0f}MB. "
                "Use GCS URI for larger files."
            )
        
        # Read and encode file
        with open(path, "rb") as f:
            content = base64.b64encode(f.read()).decode()
        
        # Build request
        request_body = {
            "rawDocument": {
                "content": content,
                "mimeType": mime_type
            },
            "processOptions": {
                "ocrConfig": {
                    "enableNativePdfParsing": True,
                    "enableImageQualityScores": True
                }
            }
        }
        
        # Add language hints if provided
        if language_hints:
            request_body["processOptions"]["ocrConfig"]["hints"] = {
                "languageHints": language_hints
            }
        
        # Call API
        url = f"{self.config.endpoint}/v1/{self.config.processor_name}:process"
        response = self._call_api(url, request_body)
        
        return self._parse_response(response)
    
    def _call_api(self, url: str, body: dict) -> dict:
        """Make authenticated API call."""
        token = self.auth.get_access_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Document AI API error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection failed: {e.reason}")
    
    def _parse_response(self, response: dict) -> OCRResult:
        """Parse Document AI response into OCRResult."""
        document = response.get("document", {})
        
        # Extract full text
        text = document.get("text", "")
        
        # Calculate average confidence across pages
        pages = document.get("pages", [])
        confidences = []
        language_codes = set()
        
        for page in pages:
            # Page-level confidence
            if "confidence" in page:
                confidences.append(page["confidence"])
            
            # Detected languages
            for lang in page.get("detectedLanguages", []):
                if lang.get("languageCode"):
                    language_codes.add(lang["languageCode"])
        
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        
        return OCRResult(
            text=text,
            confidence=avg_confidence,
            language_codes=sorted(language_codes),
            page_count=len(pages)
        )


# -----------------------------------------------------------------------------
# RESOURCESPACE SYNC INTEGRATION
# -----------------------------------------------------------------------------

def sync_to_resourcespace(
    resource_id: int,
    ocr_text: str,
    language: Optional[str] = None,
    version: Optional[str] = None
) -> bool:
    """
    Sync OCR result to ResourceSpace using sync_transcription.py.
    
    Returns True on success, False on failure.
    """
    import subprocess
    import tempfile
    
    # Write OCR text to temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        encoding="utf-8",
        delete=False
    ) as f:
        f.write(ocr_text)
        ocr_file = f.name
    
    try:
        # Build command
        script_dir = Path(__file__).parent
        sync_script = script_dir / "sync_transcription.py"
        
        cmd = [
            sys.executable,
            str(sync_script),
            "--resource-id", str(resource_id),
            "--ocr", ocr_file
        ]
        
        if language:
            cmd.extend(["--lang", language])
        
        if version:
            cmd.extend(["--version", version])
        
        # Run sync
        logger.info(f"Syncing OCR to resource {resource_id}...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=os.environ
        )
        
        if result.returncode != 0:
            logger.error(f"Sync failed: {result.stderr}")
            return False
        
        logger.info(result.stdout)
        return True
        
    finally:
        os.unlink(ocr_file)


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="process_ocr",
        description="Process documents through Google Document AI OCR",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  GOOGLE_APPLICATION_CREDENTIALS   Service account JSON key path
  DOCUMENTAI_PROJECT_ID            GCP project ID
  DOCUMENTAI_LOCATION              Processor location (default: us)
  DOCUMENTAI_PROCESSOR_ID          OCR processor ID
  
  RS_BASE_URL                      ResourceSpace URL (for sync)
  RS_USER                          API username (for sync)
  RS_API_KEY                       API private key (for sync)

Examples:
  # Process and sync to ResourceSpace
  process_ocr.py --file document.pdf --resource-id 123

  # Process with language hint
  process_ocr.py --file letter.jpg --resource-id 456 --lang de

  # Output OCR text to file (no sync)
  process_ocr.py --file document.pdf --output ocr.txt

  # Output to stdout
  process_ocr.py --file document.pdf --stdout
        """
    )
    
    # Input
    parser.add_argument("--file", "-f", required=True,
                       help="Document file path (PDF, JPG, PNG, TIFF)")
    
    # Output options
    parser.add_argument("--resource-id", "-r", type=int,
                       help="ResourceSpace resource ID (triggers sync)")
    parser.add_argument("--output", "-o",
                       help="Output OCR text to file")
    parser.add_argument("--stdout", action="store_true",
                       help="Output OCR text to stdout")
    
    # OCR options
    parser.add_argument("--lang", "-l",
                       help="Language hint (e.g., en, de, he)")
    
    # Sync options
    parser.add_argument("--version", "-v",
                       help="Processing version for sync (e.g., v1.0.0)")
    
    # Debug
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")
    parser.add_argument("--json", action="store_true",
                       help="Output result as JSON")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Validate output options
    if not any([args.resource_id, args.output, args.stdout]):
        parser.error("Specify --resource-id (to sync), --output FILE, or --stdout")
    
    try:
        # Initialize client
        config = DocumentAIConfig.from_env()
        auth = GoogleAuth()
        client = DocumentAIClient(config, auth)
        
        logger.info(f"Processing: {args.file}")
        logger.info(f"Processor: {config.processor_name}")
        
        # Process document
        language_hints = [args.lang] if args.lang else None
        result = client.process_document(args.file, language_hints=language_hints)
        
        logger.info(f"OCR complete: {len(result.text)} chars, "
                   f"{result.page_count} pages, "
                   f"confidence: {result.confidence:.1%}")
        
        if result.language_codes:
            logger.info(f"Detected languages: {', '.join(result.language_codes)}")
        
        # Handle output
        if args.json:
            output = {
                "text": result.text,
                "confidence": result.confidence,
                "languages": result.language_codes,
                "pages": result.page_count
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))
            return 0
        
        if args.stdout:
            print(result.text)
        
        if args.output:
            Path(args.output).write_text(result.text, encoding="utf-8")
            logger.info(f"OCR text written to: {args.output}")
        
        if args.resource_id:
            # Sync to ResourceSpace
            detected_lang = args.lang or result.detected_language()
            success = sync_to_resourcespace(
                resource_id=args.resource_id,
                ocr_text=result.text,
                language=detected_lang,
                version=args.version
            )
            if not success:
                return 1
        
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
