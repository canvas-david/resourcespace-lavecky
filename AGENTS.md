# AGENTS.md

## Project Overview
Docker-based ResourceSpace DAM with AI services (OCR, TTS, face detection) and archival transcription workflows.

## Architecture
```
Local: resourcespace (8080) | mariadb | minio (9000/9001)
Render: resourcespace | mysql | faces (InsightFace) | mysql-backup → R2
```

## Key Files
| Path | Purpose |
|------|---------|
| `Dockerfile` / `Dockerfile.render` | Local dev / Render production builds |
| `docker/base/Dockerfile` | Base image (apt + RS source) |
| `render.yaml` | Render deployment config |
| `entrypoint.sh` | Config generation, DB init, admin user |
| `health.php` | Render health check endpoint |
| `scripts/ocr.py` | Unified OCR (auto-detects handwriting) |
| `scripts/ocr_verify.py` | 4-model OCR consensus verification |
| `scripts/transcribe_ocr.py` | OCR→literal transcription (archival) |
| `scripts/translate_ocr.py` | Claude translation |
| `scripts/upload_file.py` | Reliable multipart file upload |
| `scripts/sync_transcription.py` | Sync transcriptions to ResourceSpace |
| `scripts/generate_tts.py` | ElevenLabs TTS generation |
| `scripts/annotate_tts.py` | Add emotion tags for TTS |
| `scripts/batch_ocr.py` | Batch OCR + translation pipeline |
| `scripts/db.sh` | SSH database helper |
| `scripts/docs/OCR_HANDLING_RULES.md` | Archival OCR rules |
| `scripts/docs/ARCHIVAL_API_REFERENCE.md` | Field IDs and API docs |
| `plugins/tts_audio/` | TTS audio plugin |

## Critical Rules

### scramble_key
**NEVER change `RS_SCRAMBLE_KEY` after files uploaded.** Makes all files inaccessible + all passwords invalid.

### Transcription Field Mutability
| Field | Name | Rule |
|-------|------|------|
| 88 | OCR Raw | **IMMUTABLE** |
| 89 | Literal | Write-once (`--force-literal` to update) |
| 96 | Formatted | Iterable |
| 101 | Translation | Iterable (`--force-translation` to update) |

### OCR Workflow
```
Raw OCR (88) → Literal (89) → Formatted (96)
  Machine       Human-verified   Reader-friendly
  IMMUTABLE     Write-once       Iterable
```

**Literal rules:** ✓ Fix OCR errors, ✓ Mark unclear `[word?]` | ✗ Don't fix author's spelling/grammar

### Multi-Model OCR Verification
| Model | Type | Best For |
|-------|------|----------|
| Document AI | Dedicated OCR | Handwriting |
| Vision API | Dedicated OCR | Typewritten |
| Claude Vision | LLM | Semantic context |
| GPT-4o Vision | LLM | Semantic context |

**Consensus:** 4/4=99%+, 3/4=95%+, 2/4=review needed

### Metadata Tabs
| Tab | Purpose | Fields |
|-----|---------|--------|
| 2. Reading | End-user content | 96, 101 |
| 3. Literal | Exact transcription | 89 |
| 4. Review | Editorial workflow | 94, 95, 98, 99 |
| 5. Technical | Processing details | 90-93, 97, 100, 102 |
| 6. Archival | Raw OCR | 88 |

### Key Field IDs
| ID | Name | Purpose |
|----|------|---------|
| 88 | ocrtext | Raw OCR (IMMUTABLE) |
| 89 | transcriptioncleaned | Literal transcription |
| 96 | transcriptionreaderformatted | Formatted version |
| 101 | englishtranslation | English translation |
| 107 | ttsscript | Emotion-tagged TTS script |

## Common Tasks

### Local Dev
```bash
cp .env.example .env && docker compose up -d  # http://localhost:8080
```

### Deploy to Render
1. Build/push base image (GitHub Actions or manual)
2. Configure GHCR credentials in Render (ghcr.io + GitHub PAT)
3. Set secrets: `MYSQL_*`, `RS_SCRAMBLE_KEY`, `RS_BASE_URL`, `RS_EMAIL_*`
4. Push to deploy (~10-20s with base image)
5. Login: `admin`/`admin` (change immediately)

### Process OCR
```bash
cd scripts && source .env
# Auto-detect engine (handwriting→Document AI, typed→Vision)
python ocr.py --file letter.jpg --output ocr.txt
# Force engine
python ocr.py --file letter.jpg --engine documentai --output ocr.txt
# 4-model verification
python ocr_verify.py --image page.jpg --output consensus.txt --report report.json
```

### Upload Files
```bash
cd scripts && source .env
python upload_file.py --resource 28 --file document.pdf
python upload_file.py -r 28 -f doc1.pdf doc2.pdf  # Multiple files
```

### Merge PDFs
```python
import fitz
merged = fitz.open()
for pdf in ["doc1.pdf", "doc2.pdf"]:
    doc = fitz.open(pdf)
    merged.insert_pdf(doc)
    doc.close()
merged.save("combined.pdf")
```

### SSH Database Access
```bash
cd scripts
./db.sh "SELECT COUNT(*) FROM resource"
./db.sh < db/create_ocr_fields.sql
ssh srv-xxx@ssh.oregon.render.com "mysql -h mysql-xbeu -u resourcespace -p\$DB_PASS resourcespace -e 'QUERY'"
```

### Sync Transcriptions
```bash
python sync_transcription.py --resource-id 123 \
  --ocr ocr.txt --literal literal.txt --formatted formatted.txt
```

### Generate TTS
```bash
python generate_tts.py --resource-id 123 --voice omi
# With emotion annotation
python annotate_tts.py --input formatted.txt --output tts_script.txt
```

## Environment Variables

### Required
`DB_HOST`, `DB_USER`, `DB_PASS`, `DB_NAME`, `RS_BASE_URL`, `RS_SCRAMBLE_KEY`, `RS_EMAIL_FROM`, `RS_EMAIL_NOTIFY`

### API Keys
| Variable | Service |
|----------|---------|
| `GOOGLE_API_KEY` | Vision API |
| `GOOGLE_APPLICATION_CREDENTIALS` | Document AI (service account JSON) |
| `DOCUMENTAI_PROJECT_ID/LOCATION/PROCESSOR_ID` | Document AI |
| `ANTHROPIC_API_KEY` | Claude (translation, transcription) |
| `OPENAI_API_KEY` | GPT-4o Vision |
| `ELEVENLABS_API_KEY` | TTS |
| `RS_API_KEY` | ResourceSpace API |

## ResourceSpace API

**Auth:** `sign = sha256(api_key + query_string)`

**Key endpoints:**
- `create_resource`, `get_resource_data`, `get_resource_field_data`
- `update_field` (returns `false` if field not linked to resource type!)
- `upload_multipart` (for file uploads)
- `add_resource_to_collection`, `create_collection`

**Database schema (node-based):**
- Field values stored in `node` table, linked via `resource_node`
- `node.ref`=ID, `node.resource_type_field`=field, `node.name`=value

```sql
-- Find node for resource+field
SELECT n.ref FROM node n JOIN resource_node rn ON n.ref=rn.node 
WHERE rn.resource=28 AND n.resource_type_field=96;
-- Update large text directly (bypasses API URL limit)
UPDATE node SET name='text' WHERE ref=584;
-- Link related resources
INSERT IGNORE INTO resource_related (resource, related) VALUES (6,7), (7,6);
```

## Plugin Development

**YAML format:** `name` (folder), `title` (display), `desc` (not description), `category` (string)

**Hooks:** `HookPluginnamePageHookpoint()` e.g., `HookTts_audioViewCustompanels()`

**Environment in PHP:** Export in `entrypoint.sh` to `/etc/apache2/envvars`

## Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| `update_field` returns false | Field not linked to resource type | `INSERT INTO resource_type_field_resource_type` |
| SSH rate limited | Render limits | Add `sleep 5` between commands |
| Files inaccessible | scramble_key changed | Restore key (no recovery if lost) |
| HTTP 414 (URL too long) | Text >5KB in API | Update `node` table directly via SSH |
| Health check fails | /login.php redirects | Use `/health.php` in render.yaml |
| 500 error | PHP error | Create debug.php with `display_errors=1` |
| Parse error with quotes | Unicode curly quotes | Use hex: `\xe2\x80\x9c` for " |
| TTS fails | Missing API key | Check `ELEVENLABS_API_KEY` in /etc/apache2/envvars |

## Backups
Daily 03:00 UTC → gzip → AES-256-CBC → Cloudflare R2 (30 day retention)
