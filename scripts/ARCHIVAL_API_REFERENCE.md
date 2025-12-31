# ResourceSpace Archival Transcription API Reference

## Field Configuration

| ID | Field | Purpose | Mutability |
|----|-------|---------|------------|
| 88 | OCR Text (Original) | Raw OCR output | **IMMUTABLE** |
| 89 | Transcription (Cleaned – Literal) | AI spelling-normalised | Write-once (force to update) |
| 96 | Transcription (Reader Formatted) | Formatted for reading | **Iterable** |
| 90 | ocr_engine | e.g., `google_document_ai` | Follows parent |
| 91 | ocr_language_detected | e.g., `en`, `de`, `he` | Follows parent |
| 92 | ocr_status | `done`, `failed`, `pending` | Follows parent |
| 93 | transcription_method | e.g., `ai_spelling_normalisation_only` | Follows parent |
| 94 | transcription_review_status | `reviewed`, `unreviewed` | Follows parent |
| 95 | transcription_notes | Free text | Follows parent |
| 97 | formatting_method | e.g., `ai_formatting_only_non_editorial` | Follows parent |
| 98 | formatting_review_status | `reviewed`, `unreviewed` (never downgrades) | Special |
| 99 | formatting_notes | Free text | Follows parent |
| 100 | processing_version | e.g., `v1.2.0` | Updated on each sync |

---

## Write Rules (Critical)

| Layer | Rule | Behaviour |
|-------|------|-----------|
| **OCR** | Immutable | Never overwrites once set |
| **Literal** | Write-once | Skipped unless `--force-literal` |
| **Formatted** | Iterable | Updates when content changes |
| **Review Status** | No downgrade | `reviewed`/`approved` are never overwritten to `unreviewed` |

---

## API Endpoints Used

### `get_resource_data`
Verify resource exists.
```
function=get_resource_data&resource={id}
```

### `get_resource_field_data`
Fetch current field values before writing.
```
function=get_resource_field_data&resource={id}
```

### `update_field`
Write single field value.
```
function=update_field&resource={id}&field={field_id}&value={text}
```

### Authentication
All requests signed with SHA256:
```
sign = sha256(api_key + query_string)
```

---

## Environment Variables

```bash
# Copy scripts/env.example to scripts/.env
RS_BASE_URL=http://localhost:8080
RS_USER=admin
RS_API_KEY=your_api_key_here
```

---

## CLI Usage

```bash
# Full sync (all three layers)
python sync_transcription.py \
  --resource-id 123 \
  --ocr ocr.txt \
  --literal literal.txt \
  --formatted formatted.txt \
  --lang de \
  --version v1.2.0

# OCR only (immutable)
python sync_transcription.py --resource-id 123 --ocr ocr.txt --lang en

# Literal only (write-once)
python sync_transcription.py --resource-id 123 --literal literal.txt

# Force literal update
python sync_transcription.py --resource-id 123 --literal corrected.txt --force-literal

# Formatted only (iterable)
python sync_transcription.py --resource-id 123 --formatted formatted_v2.txt --version v1.3.0

# Check status
python sync_transcription.py --resource-id 123 --status

# JSON output
python sync_transcription.py --resource-id 123 --status --json

# List field IDs
python sync_transcription.py --list-fields
```

---

## Python Usage

```python
from sync_transcription import TranscriptionSync, ResourceSpaceClient

client = ResourceSpaceClient(
    base_url="http://localhost:8080",
    user="admin",
    api_key="your_api_key"
)
sync = TranscriptionSync(client)

# Full sync
result = sync.sync(
    resource_id=123,
    ocr_text="raw OCR...",
    literal_text="cleaned literal...",
    formatted_text="# Reader Formatted\n\n...",
    language="en",
    version="v1.2.0",
    force_literal=False
)

# Check status
status = sync.get_status(123)
print(status["formatted"]["review_status"])  # "reviewed"
```

---

## Error Handling

| Exception | Cause | Resolution |
|-----------|-------|------------|
| `ImmutableFieldError` | OCR already set | Do not retry; field is immutable |
| `WriteOnceFieldError` | Literal already set | Use `--force-literal` if intentional |
| `ResourceNotFoundError` | Invalid resource ID | Verify resource exists in ResourceSpace |
| `AuthenticationError` | Invalid API key | Check `RS_API_KEY` |
| `APIError` | General API error | Check response body |
| `FieldNotFoundError` | Field ID doesn't exist | Run `--list-fields` to verify |

---

## Sync Result Format (JSON)

```json
{
  "resource_id": 123,
  "success": true,
  "version": "v1.2.0",
  "changes": [
    {
      "field_id": 96,
      "field_name": "Transcription (Reader Formatted)",
      "action": "updated",
      "reason": null
    },
    {
      "field_id": 98,
      "field_name": "formatting_review_status",
      "action": "unchanged",
      "reason": "kept existing 'reviewed' (no downgrade)"
    }
  ],
  "errors": []
}
```

### Action Types

| Action | Symbol | Meaning |
|--------|--------|---------|
| `created` | ✓ | Field was empty, now set |
| `updated` | ↻ | Field changed |
| `skipped` | ⊘ | Blocked by rule (immutable/write-once) |
| `unchanged` | = | Content identical, no-op |

---

## cURL Examples

### Get field values
```bash
KEY="your_api_key"
QUERY="user=admin&function=get_resource_field_data&resource=1"
SIGN=$(echo -n "${KEY}${QUERY}" | openssl dgst -sha256 | sed 's/^.* //')
curl -s -X POST "http://localhost:8080/api/?${QUERY}&sign=${SIGN}"
```

### Update field
```bash
KEY="your_api_key"
VALUE=$(python3 -c "import urllib.parse; print(urllib.parse.quote('your text'))")
QUERY="user=admin&function=update_field&resource=1&field=96&value=${VALUE}"
SIGN=$(echo -n "${KEY}${QUERY}" | openssl dgst -sha256 | sed 's/^.* //')
curl -s -X POST "http://localhost:8080/api/?${QUERY}&sign=${SIGN}"
```

---

## Archival Integrity Rules (Enforced)

1. **OCR is immutable** — `sync()` refuses to overwrite; logs "skipped immutable field"
2. **Literal is write-once** — requires explicit `--force-literal` to update
3. **Formatted is iterable** — updates when content changes; expected to evolve
4. **Review status never downgrades** — `reviewed`/`approved` preserved even when content updates
5. **All writes are idempotent** — safe to re-run; no-op if content unchanged
6. **Version tracked** — `processing_version` updated on each successful sync
