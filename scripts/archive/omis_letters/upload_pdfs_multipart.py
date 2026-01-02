#!/usr/bin/env python3
"""
Upload PDFs to ResourceSpace using multipart API

Uses the upload_multipart API endpoint which accepts file uploads
via HTTP multipart/form-data.

Reference: https://www.resourcespace.com/knowledge-base/api/upload_multipart
"""

import hashlib
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Configuration
BASE_URL = os.getenv("RS_BASE_URL", "https://resourcespace-p3o4.onrender.com")
USER = os.getenv("RS_USER", "admin")
API_KEY = os.getenv("RS_API_KEY", "")

LETTERS_DIR = Path(__file__).parent.parent / "Omi's letters"

# Resource ID -> Primary PDF mapping
PRIMARY_PDFS = {
    9: "01_intro_dear_danny_vienna_childhood.pdf",
    10: "04_vienna_cultural_life_composers.pdf",
    11: "05_cairo_vily_illness_heat.pdf",
    12: "08_1977_karen_birth_family.pdf",
}

# Resource ID -> Alternative PDFs mapping
ALT_PDFS = {
    9: ["02_intro_how_to_begin.pdf", "03_vienna_dobling_leaving_hitler.pdf"],
    11: ["06_1942_el_alamein_escape_luxor.pdf", "07_path_to_australia_mrs_lavecky.pdf"],
    12: ["09_grandchildren_blue_mountains_diary.pdf", "10_blue_mountains_health_reflections.pdf"],
}


def sign_query(query: str) -> str:
    """Sign API query with private key."""
    return hashlib.sha256((API_KEY + query).encode()).hexdigest()


def call_api(function: str, params: dict):
    """Make a standard API call (non-multipart)."""
    all_params = {"user": USER, "function": function, **params}
    query = urllib.parse.urlencode(all_params)
    sign = sign_query(query)
    
    url = f"{BASE_URL}/api/"
    post_data = urllib.parse.urlencode({
        "query": f"{query}&sign={sign}",
        "sign": sign,
        "user": USER
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=post_data, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def upload_multipart(ref: int, file_path: Path, alternative: int = 0) -> bool:
    """
    Upload file using multipart/form-data.
    
    Args:
        ref: Resource ID
        file_path: Path to file
        alternative: Alternative file ID (0 for primary file)
    
    Returns:
        True on success
    """
    import mimetypes
    import uuid
    
    # Build the query parameters (file is NOT part of signature)
    params = {
        "user": USER,
        "function": "upload_multipart",
        "ref": ref,
        "no_exif": 1,
        "revert": 0,
    }
    if alternative > 0:
        params["alternative"] = alternative
    
    query = urllib.parse.urlencode(params)
    sign = sign_query(query)
    
    # Build multipart form data
    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex[:16]}"
    
    # Read file
    file_data = file_path.read_bytes()
    filename = file_path.name
    content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    
    # Build body
    body_parts = []
    
    # Add query parameter
    body_parts.append(f'--{boundary}\r\n')
    body_parts.append('Content-Disposition: form-data; name="query"\r\n\r\n')
    body_parts.append(f'{query}&sign={sign}\r\n')
    
    # Add sign parameter
    body_parts.append(f'--{boundary}\r\n')
    body_parts.append('Content-Disposition: form-data; name="sign"\r\n\r\n')
    body_parts.append(f'{sign}\r\n')
    
    # Add user parameter
    body_parts.append(f'--{boundary}\r\n')
    body_parts.append('Content-Disposition: form-data; name="user"\r\n\r\n')
    body_parts.append(f'{USER}\r\n')
    
    # Convert text parts to bytes
    body = b''.join(p.encode() if isinstance(p, str) else p for p in body_parts)
    
    # Add file
    file_header = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f'Content-Type: {content_type}\r\n\r\n'
    ).encode()
    
    body += file_header + file_data + f'\r\n--{boundary}--\r\n'.encode()
    
    # Make request
    url = f"{BASE_URL}/api/"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = resp.status
            result = resp.read().decode("utf-8")
            return status == 204 or result == "true" or status == 200
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"    Error {e.code}: {body[:200]}")
        return False


def add_alternative_file(ref: int, name: str, filename: str, size: int) -> int:
    """Create alternative file record and return its ID."""
    import json
    
    ext = Path(filename).suffix.lstrip(".")
    result = call_api("add_alternative_file", {
        "resource": ref,
        "name": name,
        "description": "",
        "file_name": filename,
        "file_extension": ext,
        "file_size": size,
        "alt_type": ""
    })
    
    try:
        return int(result)
    except (ValueError, TypeError):
        print(f"    Failed to create alt file record: {result}")
        return 0


def main():
    if not API_KEY:
        print("Error: RS_API_KEY not set")
        print("Export it or pass via environment")
        sys.exit(1)
    
    print("=== Uploading Omi's Letters PDFs ===")
    print(f"Target: {BASE_URL}")
    print()
    
    success_count = 0
    fail_count = 0
    
    # Upload primary PDFs
    print("Uploading primary files...")
    for ref, pdf_name in PRIMARY_PDFS.items():
        pdf_path = LETTERS_DIR / pdf_name
        if not pdf_path.exists():
            print(f"  [SKIP] {pdf_name} - file not found")
            fail_count += 1
            continue
        
        print(f"  Uploading {pdf_name} -> resource {ref}...", end=" ", flush=True)
        if upload_multipart(ref, pdf_path):
            print("OK")
            success_count += 1
        else:
            print("FAILED")
            fail_count += 1
    
    print()
    
    # Upload alternative PDFs
    print("Uploading alternative files...")
    for ref, alt_pdfs in ALT_PDFS.items():
        for pdf_name in alt_pdfs:
            pdf_path = LETTERS_DIR / pdf_name
            if not pdf_path.exists():
                print(f"  [SKIP] {pdf_name} - file not found")
                fail_count += 1
                continue
            
            # Create alternative file record first
            name = pdf_path.stem
            size = pdf_path.stat().st_size
            
            print(f"  Creating alt record for {pdf_name}...", end=" ", flush=True)
            alt_id = add_alternative_file(ref, name, pdf_name, size)
            if not alt_id:
                print("FAILED")
                fail_count += 1
                continue
            print(f"ID {alt_id}")
            
            # Upload the file
            print(f"    Uploading {pdf_name} -> alt {alt_id}...", end=" ", flush=True)
            if upload_multipart(ref, pdf_path, alternative=alt_id):
                print("OK")
                success_count += 1
            else:
                print("FAILED")
                fail_count += 1
    
    print()
    print("=" * 50)
    print(f"Complete: {success_count} succeeded, {fail_count} failed")
    
    if fail_count == 0:
        print()
        print("All PDFs uploaded successfully!")
        print()
        print("View resources:")
        for ref in sorted(set(PRIMARY_PDFS.keys()) | set(ALT_PDFS.keys())):
            print(f"  Resource {ref}: {BASE_URL}/?r={ref}")
    
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
