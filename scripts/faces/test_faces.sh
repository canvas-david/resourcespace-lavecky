#!/bin/bash
# Test faces detection on a ResourceSpace resource
# Run from ResourceSpace container: bash /scripts/test_faces.sh 1

RESOURCE_ID=${1:-1}
FACES_URL="http://faces-d1tp:10000"

echo "==> Testing faces service connectivity..."
curl -s -o /dev/null -w "Status: %{http_code}\n" "$FACES_URL/"

echo ""
echo "==> Getting preview image for resource $RESOURCE_ID..."

# Find the resource's preview image in filestore
# ResourceSpace stores previews as: filestore/[scrambled_path]/[ref]_[size].jpg
PREVIEW=$(find /var/www/html/filestore -name "${RESOURCE_ID}_pre.jpg" -o -name "${RESOURCE_ID}_thm.jpg" 2>/dev/null | head -1)

if [ -z "$PREVIEW" ]; then
    # Try scr size
    PREVIEW=$(find /var/www/html/filestore -name "${RESOURCE_ID}_scr.jpg" 2>/dev/null | head -1)
fi

if [ -z "$PREVIEW" ]; then
    echo "ERROR: No preview image found for resource $RESOURCE_ID"
    echo "Searching for any file with resource ID..."
    find /var/www/html/filestore -name "${RESOURCE_ID}*" 2>/dev/null
    exit 1
fi

echo "Found: $PREVIEW"
echo ""
echo "==> Calling faces extract_faces API..."

RESPONSE=$(curl -s -X POST "$FACES_URL/extract_faces" \
    -F "file=@$PREVIEW" \
    -H "Accept: application/json")

echo "$RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$RESPONSE"

FACE_COUNT=$(echo "$RESPONSE" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")
echo ""
echo "==> Detected $FACE_COUNT face(s)"
