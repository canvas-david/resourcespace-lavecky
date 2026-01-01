#!/usr/bin/env python3
"""
ResourceSpace TTS Audio Generator

Generates text-to-speech audio from transcription text using ElevenLabs API
and uploads it as an alternative file to ResourceSpace.

Usage:
    generate_tts --resource-id 123
    generate_tts --resource-id 123 --voice "Antoni" --model "eleven_multilingual_v2"
    generate_tts --resource-id 123 --force

Environment:
    RS_BASE_URL           ResourceSpace base URL (default: http://localhost:8080)
    RS_USER               API username (default: admin)
    RS_API_KEY            API private key (required)
    ELEVENLABS_API_KEY    ElevenLabs API key (required)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
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
logger = logging.getLogger("generate_tts")


# -----------------------------------------------------------------------------
# CONFIGURATION
# -----------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldIDs:
    """ResourceSpace field IDs for transcription and TTS."""
    # Source field
    TRANSCRIPTION_FORMATTED: int = 96
    
    # TTS metadata fields
    TTS_STATUS: int = 101
    TTS_ENGINE: int = 102
    TTS_VOICE: int = 103
    TTS_GENERATED_AT: int = 104


FIELDS = FieldIDs()

# ElevenLabs defaults
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Rachel - clear, neutral voice
DEFAULT_MODEL = "eleven_multilingual_v2"

# Voice name to ID mapping (common voices)
VOICE_MAP = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "drew": "29vD33N1CtxCmqQRPOHJ",
    "clyde": "2EiwWnXFnvU5JabPnv8n",
    "paul": "5Q0t7uMcjvnagumLfvZi",
    "domi": "AZnzlk1XvdvUeBnXmlld",
    "dave": "CYw3kZ02Hs0563khs1Fj",
    "fin": "D38z5RcWu1voky8WS1ja",
    "sarah": "EXAVITQu4vr4xnSDxMaL",
    "antoni": "ErXwobaYiN019PkySvjV",
    "thomas": "GBv7mTt0atIp3Br8iCZE",
    "charlie": "IKne3meq5aSn9XLyUdCD",
    "emily": "LcfcDJNUP1GQjkzn1xUU",
    "elli": "MF3mGyEYCl7XYWbV9V6O",
    "callum": "N2lVS1w4EtoT3dr4eOWO",
    "patrick": "ODq5zmih8GrVes37Dizd",
    "harry": "SOYHLrjzK2X1ezoPC6cr",
    "liam": "TX3LPaxmHKxFdv7VOQHJ",
    "dorothy": "ThT5KcBeYPX3keUQqHPh",
    "josh": "TxGEqnHWrfWFTfGW9XjX",
    "arnold": "VR6AewLTigWG4xSOukaG",
    "charlotte": "XB0fDUnXU5powFXDhCwa",
    "matilda": "XrExE9yKIg1WjnnlVkGX",
    "matthew": "Yko7PKHZNXotIFUBG7I9",
    "james": "ZQe5CZNOzWyzPSCn5a3c",
    "joseph": "Zlb1dXrM653N07WRdFW3",
    "jessica": "cgSgspJ2msm6clMCkdW9",
    "michael": "flq6f7yk4E4fJM5XTYuZ",
    "ethan": "g5CIjZEefAph4nQFvHAz",
    "gigi": "jBpfuIE2acCO8z3wKNLl",
    "freya": "jsCqWAovK2LkecY7zXl4",
    "grace": "oWAxZDx7w5VEj9dCyTzz",
    "daniel": "onwK4e9ZLuTAKqWW03F9",
    "lily": "pFZP5JQG7iQjIQuC4Bku",
    "serena": "pMsXgVXv3BLzUgSXRplE",
    "adam": "pNInz6obpgDQGcFmaJgB",
    "nicole": "piTKgcLEGmPE4e6mEKli",
    "bill": "pqHfZKP75CvOlQylNhV4",
    "george": "JBFqnCBsd6RMkjVDRZzb",
    "sam": "yoZ06aMxZJJ28mfd3POQ",
    "glinda": "z9fAnlkpzviPz146aGWa",
    "mimi": "zrHiDhphv9ZnVXBqCLjz",
}


class TTSStatus(Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class TTSEngine(Enum):
    ELEVENLABS = "elevenlabs"


# -----------------------------------------------------------------------------
# EXCEPTIONS
# -----------------------------------------------------------------------------

class TTSError(Exception):
    """Base exception."""
    pass


class ResourceNotFoundError(TTSError):
    """Resource doesn't exist."""
    pass


class NoTranscriptionError(TTSError):
    """No transcription text available."""
    pass


class AudioExistsError(TTSError):
    """TTS audio already exists."""
    pass


class ElevenLabsError(TTSError):
    """ElevenLabs API error."""
    pass


class UploadError(TTSError):
    """Failed to upload audio."""
    pass


class AuthenticationError(TTSError):
    """API auth failure."""
    pass


class APIError(TTSError):
    """General API error."""
    pass


# -----------------------------------------------------------------------------
# API CLIENT (reused from sync_transcription.py)
# -----------------------------------------------------------------------------

class ResourceSpaceClient:
    """Low-level ResourceSpace API client."""
    
    def __init__(
        self,
        base_url: str,
        user: str,
        api_key: str,
        timeout: int = 60
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
    
    def upload_file(
        self,
        resource_id: int,
        file_path: Path,
        alternative: bool = True,
        name: str = "TTS Audio",
        description: str = "Text-to-speech audio from transcription"
    ) -> bool:
        """
        Upload a file to ResourceSpace as an alternative file.
        
        Uses add_alternative_file with file parameter for reliable alternative upload.
        """
        import base64
        
        if not alternative:
            raise NotImplementedError("Non-alternative file upload not implemented")
        
        # Read file and encode as base64 data URL
        with open(file_path, "rb") as f:
            file_data = f.read()
        
        b64_data = base64.b64encode(file_data).decode("ascii")
        data_url = f"data:audio/mpeg;base64,{b64_data}"
        
        # Use add_alternative_file with file parameter (data URL)
        # This creates the record AND copies the file in one call
        result = self.call("add_alternative_file", {
            "resource": resource_id,
            "name": name,
            "description": description,
            "file_name": file_path.name,
            "file_extension": file_path.suffix.lstrip("."),
            "file_size": len(file_data),
            "alt_type": "",
            "file": data_url
        })
        
        if result and isinstance(result, (int, str)) and str(result).isdigit():
            alt_ref = result
            logger.info(f"Created alternative file with ref: {alt_ref}")
            return True
        
        # If data URL doesn't work, try upload_file_by_url approach
        logger.warning(f"add_alternative_file with data URL failed: {result}, trying upload_file_by_url")
        
        # Fallback: Create record first, then use upload_file_by_url
        result = self.call("add_alternative_file", {
            "resource": resource_id,
            "name": name,
            "description": description,
            "file_name": file_path.name,
            "file_extension": file_path.suffix.lstrip("."),
            "file_size": len(file_data),
            "alt_type": ""
        })
        
        if not result or not str(result).isdigit():
            raise UploadError(f"Failed to create alternative file record: {result}")
        
        alt_ref = int(result)
        logger.info(f"Created alternative file record: {alt_ref}")
        
        # Try upload_file_by_url with data URL
        upload_result = self.call("upload_file_by_url", {
            "ref": resource_id,
            "url": data_url,
            "alternative": alt_ref
        })
        
        if upload_result:
            logger.info(f"Uploaded file via upload_file_by_url: {upload_result}")
            return True
        
        raise UploadError(f"Failed to upload file content: {upload_result}")


# -----------------------------------------------------------------------------
# ELEVENLABS CLIENT
# -----------------------------------------------------------------------------

class ElevenLabsClient:
    """ElevenLabs TTS API client."""
    
    API_BASE = "https://api.elevenlabs.io/v1"
    
    def __init__(self, api_key: str, timeout: int = 120):
        self.api_key = api_key
        self.timeout = timeout
        
        if not api_key:
            raise ValueError("ELEVENLABS_API_KEY is required")
    
    def text_to_speech(
        self,
        text: str,
        voice_id: str = DEFAULT_VOICE_ID,
        model_id: str = DEFAULT_MODEL,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
        use_speaker_boost: bool = True
    ) -> bytes:
        """
        Generate speech audio from text.
        
        Args:
            text: Text to convert to speech
            voice_id: ElevenLabs voice ID
            model_id: Model to use (eleven_multilingual_v2, eleven_turbo_v2, etc.)
            stability: Voice stability (0-1)
            similarity_boost: Voice clarity/similarity (0-1)
            style: Style exaggeration (0-1, only for v2 models)
            use_speaker_boost: Boost speaker similarity
        
        Returns:
            MP3 audio bytes
        """
        url = f"{self.API_BASE}/text-to-speech/{voice_id}"
        
        payload = {
            "text": text,
            "model_id": model_id,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
                "use_speaker_boost": use_speaker_boost
            }
        }
        
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise ElevenLabsError(f"ElevenLabs API error {e.code}: {body}")
        except urllib.error.URLError as e:
            raise ElevenLabsError(f"Connection failed: {e.reason}")
    
    def list_voices(self) -> List[Dict[str, Any]]:
        """List available voices."""
        url = f"{self.API_BASE}/voices"
        headers = {"xi-api-key": self.api_key}
        
        req = urllib.request.Request(url, headers=headers, method="GET")
        
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("voices", [])
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise ElevenLabsError(f"ElevenLabs API error {e.code}: {body}")


# -----------------------------------------------------------------------------
# TTS GENERATOR
# -----------------------------------------------------------------------------

class TTSGenerator:
    """
    Generates TTS audio from ResourceSpace transcription and uploads it.
    """
    
    def __init__(
        self,
        rs_client: ResourceSpaceClient,
        elevenlabs_client: ElevenLabsClient,
        fields: FieldIDs = FIELDS
    ):
        self.rs = rs_client
        self.el = elevenlabs_client
        self.fields = fields
    
    def get_transcription(self, resource_id: int) -> Optional[str]:
        """Get formatted transcription text for a resource."""
        # Verify resource exists
        res = self.rs.call("get_resource_data", {"resource": resource_id})
        if not res or (isinstance(res, dict) and res.get("error")):
            raise ResourceNotFoundError(f"Resource {resource_id} not found")
        
        # Get field data
        fields = self.rs.call("get_resource_field_data", {"resource": resource_id})
        if not isinstance(fields, list):
            raise APIError(f"Unexpected response: {fields}")
        
        for f in fields:
            fid = f.get("ref") or f.get("fref")
            if fid == self.fields.TRANSCRIPTION_FORMATTED:
                value = f.get("value", "")
                return value.strip() if value else None
        
        return None
    
    def get_tts_status(self, resource_id: int) -> Optional[str]:
        """Get current TTS status for a resource."""
        fields = self.rs.call("get_resource_field_data", {"resource": resource_id})
        if not isinstance(fields, list):
            return None
        
        for f in fields:
            fid = f.get("ref") or f.get("fref")
            if fid == self.fields.TTS_STATUS:
                value = f.get("value", "")
                return value.strip() if value else None
        
        return None
    
    def get_alternative_files(self, resource_id: int) -> List[Dict[str, Any]]:
        """Get alternative files for a resource."""
        result = self.rs.call("get_alternative_files", {"resource": resource_id})
        if isinstance(result, list):
            return result
        return []
    
    def has_tts_audio(self, resource_id: int) -> bool:
        """Check if resource already has TTS audio."""
        alternatives = self.get_alternative_files(resource_id)
        for alt in alternatives:
            name = alt.get("name", "").lower()
            desc = alt.get("description", "").lower()
            ext = alt.get("file_extension", "").lower()
            if "tts" in name or "tts" in desc or (ext == "mp3" and "audio" in name.lower()):
                return True
        return False
    
    def update_field(self, resource_id: int, field_id: int, value: str) -> bool:
        """Update a metadata field."""
        result = self.rs.call("update_field", {
            "resource": resource_id,
            "field": field_id,
            "value": value
        })
        return result is True
    
    def generate(
        self,
        resource_id: int,
        voice: str = DEFAULT_VOICE_ID,
        model: str = DEFAULT_MODEL,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Generate TTS audio for a resource.
        
        Args:
            resource_id: Target resource
            voice: Voice ID or name
            model: ElevenLabs model ID
            force: Regenerate even if audio exists
        
        Returns:
            Result dict with status and details
        """
        result = {
            "resource_id": resource_id,
            "success": False,
            "message": "",
            "voice": voice,
            "model": model
        }
        
        logger.info(f"Processing resource {resource_id}")
        
        # Check if TTS already exists
        if not force and self.has_tts_audio(resource_id):
            logger.info("TTS audio already exists, use --force to regenerate")
            result["message"] = "TTS audio already exists"
            result["success"] = True
            result["skipped"] = True
            return result
        
        # Get transcription text
        text = self.get_transcription(resource_id)
        if not text:
            logger.error("No formatted transcription found")
            self.update_field(resource_id, self.fields.TTS_STATUS, TTSStatus.FAILED.value)
            result["message"] = "No formatted transcription available"
            return result
        
        logger.info(f"Found transcription: {len(text)} characters")
        
        # Resolve voice name to ID
        voice_id = voice
        if voice.lower() in VOICE_MAP:
            voice_id = VOICE_MAP[voice.lower()]
            logger.info(f"Resolved voice '{voice}' to ID: {voice_id}")
        
        # Update status to pending
        self.update_field(resource_id, self.fields.TTS_STATUS, TTSStatus.PENDING.value)
        
        try:
            # Generate audio
            logger.info(f"Generating TTS with voice={voice_id}, model={model}")
            audio_data = self.el.text_to_speech(
                text=text,
                voice_id=voice_id,
                model_id=model
            )
            logger.info(f"Generated audio: {len(audio_data)} bytes")
            
            # Save to temp file and upload
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = Path(tmp.name)
            
            try:
                logger.info("Uploading to ResourceSpace as alternative file")
                self.rs.upload_file(
                    resource_id=resource_id,
                    file_path=tmp_path,
                    alternative=True,
                    name="TTS Audio",
                    description=f"Text-to-speech audio (voice: {voice}, model: {model})"
                )
            finally:
                tmp_path.unlink()  # Clean up temp file
            
            # Update metadata
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
            self.update_field(resource_id, self.fields.TTS_STATUS, TTSStatus.DONE.value)
            self.update_field(resource_id, self.fields.TTS_ENGINE, TTSEngine.ELEVENLABS.value)
            self.update_field(resource_id, self.fields.TTS_VOICE, voice)
            self.update_field(resource_id, self.fields.TTS_GENERATED_AT, timestamp)
            
            result["success"] = True
            result["message"] = f"Generated {len(audio_data)} bytes of audio"
            result["timestamp"] = timestamp
            logger.info(f"✓ TTS generation complete for resource {resource_id}")
            
        except ElevenLabsError as e:
            logger.error(f"ElevenLabs error: {e}")
            self.update_field(resource_id, self.fields.TTS_STATUS, TTSStatus.FAILED.value)
            result["message"] = str(e)
        except UploadError as e:
            logger.error(f"Upload error: {e}")
            self.update_field(resource_id, self.fields.TTS_STATUS, TTSStatus.FAILED.value)
            result["message"] = str(e)
        except Exception as e:
            logger.exception("Unexpected error")
            self.update_field(resource_id, self.fields.TTS_STATUS, TTSStatus.FAILED.value)
            result["message"] = f"Unexpected error: {e}"
        
        return result


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="generate_tts",
        description="Generate TTS audio from ResourceSpace transcription using ElevenLabs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment variables:
  RS_BASE_URL           ResourceSpace URL (default: http://localhost:8080)
  RS_USER               API username (default: admin)
  RS_API_KEY            API private key (required)
  ELEVENLABS_API_KEY    ElevenLabs API key (required)

Examples:
  # Generate TTS for a resource
  generate_tts --resource-id 123
  
  # Use specific voice
  generate_tts --resource-id 123 --voice rachel
  
  # Force regeneration
  generate_tts --resource-id 123 --force
  
  # Use different model
  generate_tts --resource-id 123 --model eleven_turbo_v2
  
  # List available voices
  generate_tts --list-voices
        """
    )
    
    # Connection
    parser.add_argument("--url", default=os.getenv("RS_BASE_URL", "http://localhost:8080"),
                       help="ResourceSpace URL")
    parser.add_argument("--user", default=os.getenv("RS_USER", "admin"),
                       help="API user")
    parser.add_argument("--key", default=os.getenv("RS_API_KEY"),
                       help="ResourceSpace API key (or RS_API_KEY env var)")
    parser.add_argument("--elevenlabs-key", default=os.getenv("ELEVENLABS_API_KEY"),
                       help="ElevenLabs API key (or ELEVENLABS_API_KEY env var)")
    
    # Target
    parser.add_argument("--resource-id", type=int, help="Resource ID")
    
    # TTS options
    parser.add_argument("--voice", default="rachel",
                       help="Voice name or ID (default: rachel)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                       help=f"ElevenLabs model (default: {DEFAULT_MODEL})")
    parser.add_argument("--force", action="store_true",
                       help="Regenerate even if TTS already exists")
    
    # Actions
    parser.add_argument("--list-voices", action="store_true",
                       help="List available ElevenLabs voices")
    parser.add_argument("--json", action="store_true",
                       help="Output as JSON")
    
    args = parser.parse_args()
    
    # List voices action (only needs ElevenLabs key)
    if args.list_voices:
        if not args.elevenlabs_key:
            parser.error("--elevenlabs-key or ELEVENLABS_API_KEY required")
        
        el_client = ElevenLabsClient(args.elevenlabs_key)
        voices = el_client.list_voices()
        
        if args.json:
            print(json.dumps(voices, indent=2))
        else:
            print(f"\n{'Voice Name':<25} {'Voice ID':<25} Labels")
            print("-" * 80)
            for v in voices:
                labels = ", ".join(f"{k}={v}" for k, v in v.get("labels", {}).items())
                print(f"{v['name']:<25} {v['voice_id']:<25} {labels}")
            print(f"\nTotal: {len(voices)} voices")
            print("\nBuilt-in voice shortcuts:")
            for name in sorted(VOICE_MAP.keys()):
                print(f"  {name}")
        return 0
    
    # Validate required args for generation
    if not args.key:
        parser.error("--key or RS_API_KEY environment variable required")
    if not args.elevenlabs_key:
        parser.error("--elevenlabs-key or ELEVENLABS_API_KEY environment variable required")
    if not args.resource_id:
        parser.error("--resource-id required")
    
    # Create clients
    rs_client = ResourceSpaceClient(args.url, args.user, args.key)
    el_client = ElevenLabsClient(args.elevenlabs_key)
    generator = TTSGenerator(rs_client, el_client)
    
    # Generate TTS
    try:
        result = generator.generate(
            resource_id=args.resource_id,
            voice=args.voice,
            model=args.model,
            force=args.force
        )
        
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print()
            print("=" * 50)
            if result["success"]:
                if result.get("skipped"):
                    print(f"⊘ {result['message']}")
                else:
                    print(f"✓ {result['message']}")
            else:
                print(f"✗ Failed: {result['message']}")
        
        return 0 if result["success"] else 1
        
    except TTSError as e:
        logger.error(str(e))
        return 1
    except Exception as e:
        logger.exception("Unexpected error")
        return 1


if __name__ == "__main__":
    sys.exit(main())
