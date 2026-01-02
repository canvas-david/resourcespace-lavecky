#!/usr/bin/env python3
"""
Upload files to ResourceSpace resources.

Usage:
    # Upload single file
    upload_file.py --resource 13 --file document.pdf

    # Upload multiple files to one resource (first = primary, rest = alternatives)
    upload_file.py --resource 13 --file doc1.pdf doc2.pdf doc3.pdf

    # Upload to multiple resources
    upload_file.py --resource 13 --file doc1.pdf --resource 14 --file doc2.pdf

Environment:
    RS_BASE_URL - ResourceSpace base URL
    RS_API_KEY  - API key
    RS_USER     - Username (default: admin)
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def get_env():
    """Get required environment variables."""
    base_url = os.environ.get('RS_BASE_URL')
    api_key = os.environ.get('RS_API_KEY')
    user = os.environ.get('RS_USER', 'admin')
    
    if not base_url or not api_key:
        print("ERROR: RS_BASE_URL and RS_API_KEY must be set", file=sys.stderr)
        sys.exit(1)
    
    return base_url.rstrip('/'), api_key, user


def upload_file(base_url: str, api_key: str, user: str, resource_id: int, filepath: Path) -> dict:
    """Upload a file to a ResourceSpace resource using multipart upload."""
    import mimetypes
    
    # Build query parameters
    params = {
        'user': user,
        'function': 'upload_multipart',
        'ref': str(resource_id),
        'no_exif': '1',
        'revert': '0',
    }
    
    # Generate signature from query string
    query_string = urllib.parse.urlencode(params)
    sign = hashlib.sha256((api_key + query_string).encode()).hexdigest()
    
    # Read file
    with open(filepath, 'rb') as f:
        file_data = f.read()
    
    # Build multipart form data
    boundary = '----ResourceSpaceUpload'
    filename = filepath.name
    mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
    
    body_parts = []
    
    # Add query parameter
    body_parts.append(f'--{boundary}'.encode())
    body_parts.append(b'Content-Disposition: form-data; name="query"')
    body_parts.append(b'')
    body_parts.append(query_string.encode())
    
    # Add sign parameter
    body_parts.append(f'--{boundary}'.encode())
    body_parts.append(b'Content-Disposition: form-data; name="sign"')
    body_parts.append(b'')
    body_parts.append(sign.encode())
    
    # Add user parameter
    body_parts.append(f'--{boundary}'.encode())
    body_parts.append(b'Content-Disposition: form-data; name="user"')
    body_parts.append(b'')
    body_parts.append(user.encode())
    
    # Add file
    body_parts.append(f'--{boundary}'.encode())
    body_parts.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode())
    body_parts.append(f'Content-Type: {mime_type}'.encode())
    body_parts.append(b'')
    body_parts.append(file_data)
    
    # End boundary
    body_parts.append(f'--{boundary}--'.encode())
    body_parts.append(b'')
    
    body = b'\r\n'.join(body_parts)
    
    # Make request
    url = f'{base_url}/api/'
    req = urllib.request.Request(url, data=body, method='POST')
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            response_data = resp.read().decode()
            try:
                return json.loads(response_data)
            except json.JSONDecodeError:
                return {'status': 'success', 'raw': response_data}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        return {'status': 'fail', 'code': e.code, 'error': error_body}
    except Exception as e:
        return {'status': 'fail', 'error': str(e)}


def main():
    parser = argparse.ArgumentParser(description='Upload files to ResourceSpace')
    parser.add_argument('--resource', '-r', type=int, required=True, help='Resource ID')
    parser.add_argument('--file', '-f', nargs='+', required=True, help='File(s) to upload')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    
    args = parser.parse_args()
    base_url, api_key, user = get_env()
    
    files = [Path(f) for f in args.file]
    
    # Validate files exist
    for f in files:
        if not f.exists():
            print(f"ERROR: File not found: {f}", file=sys.stderr)
            sys.exit(1)
    
    print(f"Uploading to resource {args.resource}...")
    
    for i, filepath in enumerate(files):
        file_type = "Primary" if i == 0 else f"Alternative #{i}"
        print(f"  {file_type}: {filepath.name} ({filepath.stat().st_size // 1024} KB)")
        
        result = upload_file(base_url, api_key, user, args.resource, filepath)
        
        if args.verbose:
            print(f"    Response: {result}")
        
        if result.get('status') == 'fail':
            print(f"    ERROR: {result.get('error', result)}")
            sys.exit(1)
        else:
            print(f"    OK")
    
    print("Done!")
    return 0


if __name__ == '__main__':
    sys.exit(main())
