#!/usr/bin/env python3
"""
Unified OCR Script with Auto-Detection

Automatically detects handwritten vs typewritten documents and routes to the
optimal OCR engine:
- Handwritten content → Document AI (better accuracy)
- Typewritten content → Vision API (faster, simpler)

Usage:
    # Auto-detect and route to best engine
    ocr.py --file document.jpg --output ocr.txt

    # Force specific engine
    ocr.py --file document.jpg --engine documentai --output ocr.txt
    ocr.py --file document.jpg --engine vision --output ocr.txt

    # With language hint
    ocr.py --file letter.jpg --lang pl --output ocr.txt

Environment:
    GOOGLE_API_KEY                   Google Cloud API key (Vision API)
    GOOGLE_APPLICATION_CREDENTIALS   Service account JSON (Document AI)
    DOCUMENTAI_PROJECT_ID            GCP project ID
    DOCUMENTAI_LOCATION              Processor location (us, eu)
    DOCUMENTAI_PROCESSOR_ID          OCR processor ID
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# -----------------------------------------------------------------------------
# PUBLIC API - Available for import by other modules
# -----------------------------------------------------------------------------

__all__ = [
    "OCRResult",
    "VisionAPIClient",
    "DocumentAIClient",
    "DocumentAIConfig",
    "GoogleAuth",
    "OCRProcessor",
    "SUPPORTED_TYPES",
    "HANDWRITING_THRESHOLD",
]

# -----------------------------------------------------------------------------
# LOGGING
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("ocr")

# -----------------------------------------------------------------------------
# CONSTANTS
# -----------------------------------------------------------------------------

HANDWRITING_THRESHOLD = 0.30  # Route to Document AI if >30% handwriting blocks

SUPPORTED_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".pdf": "application/pdf",
}

LANGUAGE_NAMES = {
    "pl": "Polish",
    "he": "Hebrew",
    "yi": "Yiddish",
    "de": "German",
    "ru": "Russian",
    "en": "English",
}


# -----------------------------------------------------------------------------
# OCR RESULT
# -----------------------------------------------------------------------------

@dataclass
class OCRResult:
    """Result from OCR processing."""
    text: str
    confidence: float
    engine: str
    language_codes: List[str]
    page_count: int
    handwriting_ratio: float = 0.0

    def detected_language(self) -> Optional[str]:
        """Return primary detected language code."""
        return self.language_codes[0] if self.language_codes else None


# -----------------------------------------------------------------------------
# VISION API CLIENT
# -----------------------------------------------------------------------------

class VisionAPIClient:
    """Google Cloud Vision API client."""

    API_URL = "https://vision.googleapis.com/v1/images:annotate"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def detect_handwriting_ratio(self, image_path: str) -> float:
        """
        Quick check to detect proportion of handwritten content.

        Returns ratio of handwriting blocks (0.0 to 1.0).
        """
        path = Path(image_path)
        with open(path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        request_body = {
            "requests": [{
                "image": {"content": image_data},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}]
            }]
        }

        response = self._call_api(request_body)
        return self._calculate_handwriting_ratio(response)

    def extract_text(
        self,
        image_path: str,
        language_hints: Optional[List[str]] = None
    ) -> OCRResult:
        """Extract text using Vision API."""
        path = Path(image_path)
        with open(path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        request_body = {
            "requests": [{
                "image": {"content": image_data},
                "features": [{"type": "DOCUMENT_TEXT_DETECTION", "maxResults": 1}]
            }]
        }

        if language_hints:
            request_body["requests"][0]["imageContext"] = {
                "languageHints": language_hints
            }

        response = self._call_api(request_body)
        text, confidence, languages = self._parse_response(response)
        handwriting_ratio = self._calculate_handwriting_ratio(response)

        return OCRResult(
            text=text,
            confidence=confidence,
            engine="vision",
            language_codes=languages,
            page_count=1,
            handwriting_ratio=handwriting_ratio
        )

    def _call_api(self, body: dict) -> dict:
        """Make API call to Google Vision."""
        url = f"{self.API_URL}?key={self.api_key}"
        headers = {"Content-Type": "application/json"}
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            try:
                error_json = json.loads(error_body)
                error_msg = error_json.get("error", {}).get("message", error_body)
            except json.JSONDecodeError:
                error_msg = error_body
            raise RuntimeError(f"Vision API error {e.code}: {error_msg}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Connection failed: {e.reason}")

    def _parse_response(self, response: dict) -> Tuple[str, float, List[str]]:
        """Parse Vision API response."""
        responses = response.get("responses", [])
        if not responses:
            return "", 0.0, []

        result = responses[0]
        if "error" in result:
            error = result["error"]
            raise RuntimeError(f"Vision API error: {error.get('message', str(error))}")

        full_text = result.get("fullTextAnnotation", {})
        text = full_text.get("text", "")

        # Calculate confidence and collect languages
        pages = full_text.get("pages", [])
        confidences = []
        languages = set()

        for page in pages:
            for block in page.get("blocks", []):
                if "confidence" in block:
                    confidences.append(block["confidence"])
            # Detected languages
            for lang in page.get("property", {}).get("detectedLanguages", []):
                if lang.get("languageCode"):
                    languages.add(lang["languageCode"])

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        return text, avg_confidence, sorted(languages)

    def _calculate_handwriting_ratio(self, response: dict) -> float:
        """Calculate ratio of handwriting blocks in response."""
        responses = response.get("responses", [])
        if not responses:
            return 0.0

        result = responses[0]
        full_text = result.get("fullTextAnnotation", {})
        pages = full_text.get("pages", [])

        total_blocks = 0
        handwriting_blocks = 0

        for page in pages:
            for block in page.get("blocks", []):
                total_blocks += 1
                # Vision API marks handwriting with blockType
                block_type = block.get("blockType", "")
                if block_type == "HANDWRITING":
                    handwriting_blocks += 1

        if total_blocks == 0:
            return 0.0

        return handwriting_blocks / total_blocks


# -----------------------------------------------------------------------------
# DOCUMENT AI CLIENT
# -----------------------------------------------------------------------------

@dataclass
class DocumentAIConfig:
    """Document AI configuration."""
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

        return cls(project_id=project_id, location=location, processor_id=processor_id)

    @property
    def endpoint(self) -> str:
        return f"https://{self.location}-documentai.googleapis.com"

    @property
    def processor_name(self) -> str:
        return f"projects/{self.project_id}/locations/{self.location}/processors/{self.processor_id}"


class GoogleAuth:
    """Google Cloud authentication using service account."""

    def __init__(self):
        self._token: Optional[str] = None
        self._token_expiry: float = 0

    def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        import time

        if self._token and time.time() < self._token_expiry - 60:
            return self._token

        # Try metadata server first (GCP environments)
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

        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if not creds_path:
            raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable required")

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

        def b64_encode(data: dict) -> str:
            return base64.urlsafe_b64encode(
                json.dumps(data, separators=(",", ":")).encode()
            ).rstrip(b"=").decode()

        header_b64 = b64_encode(header)
        payload_b64 = b64_encode(payload)
        signing_input = f"{header_b64}.{payload_b64}"

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
        """Sign message with RS256."""
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            private_key = serialization.load_pem_private_key(
                private_key_pem.encode(), password=None
            )
            signature = private_key.sign(
                message.encode(), padding.PKCS1v15(), hashes.SHA256()
            )
            return base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
        except ImportError:
            pass

        # Fallback to openssl
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


class DocumentAIClient:
    """Google Cloud Document AI client."""

    MAX_INLINE_SIZE = 20 * 1024 * 1024  # 20MB

    def __init__(self, config: DocumentAIConfig, auth: GoogleAuth):
        self.config = config
        self.auth = auth

    def extract_text(
        self,
        image_path: str,
        language_hints: Optional[List[str]] = None
    ) -> OCRResult:
        """Extract text using Document AI."""
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {image_path}")

        suffix = path.suffix.lower()
        mime_type = SUPPORTED_TYPES.get(suffix)
        if not mime_type:
            raise ValueError(f"Unsupported file type: {suffix}")

        file_size = path.stat().st_size
        if file_size > self.MAX_INLINE_SIZE:
            raise ValueError(f"File too large: {file_size / 1024 / 1024:.1f}MB (max 20MB)")

        with open(path, "rb") as f:
            content = base64.b64encode(f.read()).decode()

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

        if language_hints:
            request_body["processOptions"]["ocrConfig"]["hints"] = {
                "languageHints": language_hints
            }

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
        """Parse Document AI response."""
        document = response.get("document", {})
        text = document.get("text", "")

        pages = document.get("pages", [])
        confidences = []
        language_codes = set()

        for page in pages:
            if "confidence" in page:
                confidences.append(page["confidence"])
            for lang in page.get("detectedLanguages", []):
                if lang.get("languageCode"):
                    language_codes.add(lang["languageCode"])

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        return OCRResult(
            text=text,
            confidence=avg_confidence,
            engine="documentai",
            language_codes=sorted(language_codes),
            page_count=len(pages)
        )


# -----------------------------------------------------------------------------
# UNIFIED OCR PROCESSOR
# -----------------------------------------------------------------------------

class OCRProcessor:
    """Unified OCR processor with auto-detection."""

    def __init__(
        self,
        vision_api_key: Optional[str] = None,
        documentai_config: Optional[DocumentAIConfig] = None
    ):
        self.vision_client = VisionAPIClient(vision_api_key) if vision_api_key else None
        self.documentai_client = None

        if documentai_config:
            auth = GoogleAuth()
            self.documentai_client = DocumentAIClient(documentai_config, auth)

    def process(
        self,
        image_path: str,
        engine: str = "auto",
        language_hints: Optional[List[str]] = None
    ) -> OCRResult:
        """
        Process document through OCR.

        Args:
            image_path: Path to image file
            engine: 'auto', 'vision', or 'documentai'
            language_hints: Language codes for better accuracy

        Returns:
            OCRResult with extracted text and metadata
        """
        # Validate file
        path = Path(image_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {image_path}")

        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_TYPES:
            raise ValueError(f"Unsupported file type: {suffix}")

        # Determine engine
        if engine == "auto":
            engine = self._detect_best_engine(image_path)
            logger.info(f"Auto-detected engine: {engine}")

        # Route to appropriate engine
        if engine == "documentai":
            if not self.documentai_client:
                raise ValueError(
                    "Document AI not configured. Set GOOGLE_APPLICATION_CREDENTIALS, "
                    "DOCUMENTAI_PROJECT_ID, and DOCUMENTAI_PROCESSOR_ID"
                )
            return self.documentai_client.extract_text(image_path, language_hints)
        else:
            if not self.vision_client:
                raise ValueError("Vision API not configured. Set GOOGLE_API_KEY")
            return self.vision_client.extract_text(image_path, language_hints)

    def _detect_best_engine(self, image_path: str) -> str:
        """Detect whether document is handwritten and choose best engine."""
        # Need Vision API for detection
        if not self.vision_client:
            logger.warning("Vision API not available for detection, defaulting to documentai")
            return "documentai" if self.documentai_client else "vision"

        # If Document AI not available, use Vision
        if not self.documentai_client:
            logger.debug("Document AI not configured, using Vision API")
            return "vision"

        try:
            ratio = self.vision_client.detect_handwriting_ratio(image_path)
            logger.info(f"Handwriting ratio: {ratio:.1%}")

            if ratio > HANDWRITING_THRESHOLD:
                logger.info(f"Detected handwritten content ({ratio:.1%} > {HANDWRITING_THRESHOLD:.0%})")
                return "documentai"
            else:
                return "vision"
        except Exception as e:
            logger.warning(f"Detection failed, defaulting to vision: {e}")
            return "vision"


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="ocr",
        description="Unified OCR with auto-detection for handwritten content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  GOOGLE_API_KEY                   Vision API key
  GOOGLE_APPLICATION_CREDENTIALS   Document AI service account JSON
  DOCUMENTAI_PROJECT_ID            GCP project ID
  DOCUMENTAI_LOCATION              Processor location (us, eu)
  DOCUMENTAI_PROCESSOR_ID          OCR processor ID

Examples:
  # Auto-detect and use best engine
  ocr.py --file letter.jpg --output ocr.txt

  # Force Document AI for known handwritten content
  ocr.py --file letter.jpg --engine documentai --output ocr.txt

  # Use Vision API for typewritten documents
  ocr.py --file typed_doc.jpg --engine vision --output ocr.txt

  # With language hint
  ocr.py --file letter.jpg --lang pl --output ocr.txt

  # JSON output with metadata
  ocr.py --file letter.jpg --json
        """
    )

    parser.add_argument("--file", "-f", required=True,
                       help="Image file path (JPG, PNG, TIFF, PDF)")
    parser.add_argument("--engine", "-e", choices=["auto", "vision", "documentai"],
                       default="auto", help="OCR engine (default: auto)")
    parser.add_argument("--lang", "-l",
                       help="Language hint (pl, he, de, etc.)")
    parser.add_argument("--output", "-o", metavar="FILE",
                       help="Output text file")
    parser.add_argument("--stdout", action="store_true",
                       help="Output to stdout")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON with metadata")
    parser.add_argument("--debug", action="store_true",
                       help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if not args.output and not args.stdout and not args.json:
        parser.error("Specify --output FILE, --stdout, or --json")

    try:
        # Initialize processor with available credentials
        vision_api_key = os.getenv("GOOGLE_API_KEY")
        documentai_config = None

        try:
            documentai_config = DocumentAIConfig.from_env()
        except ValueError as e:
            if args.engine == "documentai":
                raise
            logger.debug(f"Document AI not configured: {e}")

        if not vision_api_key and not documentai_config:
            raise ValueError(
                "No OCR credentials configured. Set GOOGLE_API_KEY (Vision) or "
                "Document AI credentials (GOOGLE_APPLICATION_CREDENTIALS, etc.)"
            )

        processor = OCRProcessor(
            vision_api_key=vision_api_key,
            documentai_config=documentai_config
        )

        logger.info(f"Processing: {args.file}")
        if args.lang:
            logger.info(f"Language hint: {LANGUAGE_NAMES.get(args.lang, args.lang)}")

        language_hints = [args.lang] if args.lang else None
        result = processor.process(args.file, engine=args.engine, language_hints=language_hints)

        logger.info(f"OCR complete: {len(result.text)} chars, engine: {result.engine}")
        logger.info(f"Confidence: {result.confidence:.1%}")
        if result.language_codes:
            logger.info(f"Detected languages: {', '.join(result.language_codes)}")

        if args.json:
            output = {
                "file": args.file,
                "engine": result.engine,
                "language": args.lang,
                "detected_languages": result.language_codes,
                "chars": len(result.text),
                "confidence": result.confidence,
                "pages": result.page_count,
                "handwriting_ratio": result.handwriting_ratio,
                "text": result.text
            }
            print(json.dumps(output, indent=2, ensure_ascii=False))

        if args.stdout and not args.json:
            print(result.text)

        if args.output:
            Path(args.output).write_text(result.text, encoding="utf-8")
            logger.info(f"Text written to: {args.output}")

        return 0

    except Exception as e:
        logger.error(str(e))
        if args.debug:
            logger.exception("Full traceback:")
        return 1


if __name__ == "__main__":
    sys.exit(main())
