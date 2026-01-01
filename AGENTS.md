# AGENTS.md

## Project Overview

Docker-based deployment for ResourceSpace DAM (Digital Asset Management) with environment-driven configuration, AI services, and archival transcription workflows.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Compose (Local)                   │
├─────────────────────────────────────────────────────────────────┤
│  resourcespace     │  mariadb          │  minio                 │
│  (PHP/Apache)      │  (Database)       │  (S3-compatible)       │
│  Port: 8080        │  Internal         │  Port: 9000/9001       │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        Render.com (Production)                  │
├─────────────────────────────────────────────────────────────────┤
│  resourcespace     │  mysql            │  faces                 │
│  (Web Service)     │  (Private Svc)    │  (Private Svc)         │
│                    │                   │  InsightFace AI        │
├─────────────────────────────────────────────────────────────────┤
│  mysql-backup (Cron Job) → Cloudflare R2                        │
└─────────────────────────────────────────────────────────────────┘
```

## Key Files

| Path | Purpose |
|------|---------|
| `Dockerfile` | Main ResourceSpace container |
| `docker-compose.yaml` | Local development stack |
| `render.yaml` | Render.com production deployment |
| `docker/config.php.template` | Config template with env var placeholders |
| `entrypoint.sh` | Generates config.php, auto-inits DB, creates admin user |
| `docker/mysql/` | MySQL container for Render |
| `docker/backup/` | Backup cron job with R2 upload |
| `docker/faces/` | InsightFace AI service |
| `plugins/tts_audio/` | TTS audio generation plugin |
| `scripts/db.sh` | Render MySQL helper (SSH database access) |
| `scripts/create_ocr_fields.sql` | OCR/transcription field schema |
| `scripts/process_ocr.py` | Google Document AI OCR processor |
| `scripts/sync_transcription.py` | Archival transcription sync CLI |
| `scripts/generate_tts.py` | ElevenLabs TTS audio generator |

## Critical Rules

### scramble_key
**NEVER change `RS_SCRAMBLE_KEY` after files are uploaded.** This key generates file storage paths AND is used in password hashing. Changing it makes:
- All existing files inaccessible
- All user passwords invalid

### Password Hashing
ResourceSpace uses a multi-layer password hash:
```
password_hash(hash_hmac('sha256', 'RS{username}{password}', scramble_key), PASSWORD_DEFAULT)
```

To manually set a user password:
```bash
# Generate hash (run on resourcespace container)
php -r "include '/var/www/html/include/config.php'; \$pass = hash_hmac('sha256', 'RS{USERNAME}{PASSWORD}', \$scramble_key); echo password_hash(\$pass, PASSWORD_DEFAULT) . PHP_EOL;"

# Update in database
mysql -h mysql-xbeu -u resourcespace -p resourcespace -e "UPDATE user SET password='HASH_HERE' WHERE username='USERNAME';"
```

### Transcription Field Mutability
The sync_transcription.py enforces archival integrity:

| Field | Rule |
|-------|------|
| OCR Text (Original) | **IMMUTABLE** - never overwrite |
| Transcription (Literal) | Write-once, `--force-literal` to update |
| Transcription (Formatted) | Iterable - updates allowed |
| Review Status | Never downgrades from `reviewed`/`approved` |

### Metadata Tab Structure
Fields are organized into tabs for different user workflows:

| Tab | Purpose | Fields |
|-----|---------|--------|
| 1. Default | Standard asset metadata | Date, Filename, Keywords, etc. |
| 2. Transcription | Readable content | Literal Transcription, Reader-Friendly Version |
| 3. Review | Editorial workflow | Transcription Status, Notes, Formatting Status, Notes |
| 4. Technical | Processing details | OCR Status, Engine, Language, Methods, Pipeline Version |
| 5. Archival | Raw source data | Original OCR Output |

Tab names are prefixed with numbers to force correct sort order (ResourceSpace sorts alphabetically).

## Common Tasks

### Local Development
```bash
cp .env.example .env
# Edit .env with required values
docker compose build
docker compose up -d
# Access at http://localhost:8080
```

### Deploy to Render
1. Set secrets in Render dashboard (see README.md):
   - `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` on mysql service
   - `RS_SCRAMBLE_KEY`, `RS_BASE_URL`, `RS_EMAIL_*` on resourcespace service
2. Push to trigger auto-deploy
3. Database auto-initializes on first run (no setup wizard needed)
4. Login with `admin` / `admin` and change password immediately
5. Create backup user in MySQL for backups
6. Configure AI Faces plugin URL: `http://faces:8001`

### Process OCR with Document AI
```bash
cd scripts
# Process and sync to ResourceSpace
python process_ocr.py --file document.pdf --resource-id 123 --lang de

# Output to file only
python process_ocr.py --file document.pdf --output ocr.txt
```

### Sync Transcriptions
```bash
cd scripts
python sync_transcription.py --resource-id 123 \
 --ocr ocr.txt --literal literal.txt --formatted formatted.txt \
 --lang de --version v1.2.0
```

### Check Transcription Status
```bash
python scripts/sync_transcription.py --resource-id 123 --status
```

### SSH Database Access (Render Production)
SSH is enabled on the resourcespace container for direct database access.

**Prerequisites:**
1. Add your SSH public key to Render: Dashboard → Account Settings → SSH Public Keys
2. Your key: `~/.ssh/id_ed25519.pub` or `~/.ssh/id_rsa.pub`

**Using the db.sh helper:**
```bash
cd scripts

# Run a single query
./db.sh "SELECT COUNT(*) FROM resource"

# Run a SQL file
./db.sh < create_ocr_fields.sql

# Interactive MySQL session
./db.sh
```

**Direct SSH access:**
```bash
# SSH into container
ssh srv-d5acinkhg0os73cr9gq0@ssh.oregon.render.com

# Run MySQL command directly
ssh srv-d5acinkhg0os73cr9gq0@ssh.oregon.render.com \
  "mysql -h mysql-xbeu -u resourcespace -p\$DB_PASS resourcespace -e 'SHOW TABLES'"
```

**Common database queries:**
```bash
# List all metadata tabs
./db.sh "SELECT * FROM tab ORDER BY order_by"

# List transcription fields
./db.sh "SELECT ref, name, title, tab FROM resource_type_field WHERE ref BETWEEN 88 AND 100"

# Check resource field data
./db.sh "SELECT * FROM resource_data WHERE resource = 123"

# Update field order
./db.sh "UPDATE resource_type_field SET order_by = 10 WHERE ref = 89"
```

### Generate TTS Audio
```bash
cd scripts
# Generate TTS from formatted transcription
python generate_tts.py --resource-id 123 --voice rachel

# Combined sync + TTS generation
python sync_transcription.py --resource-id 123 \
 --formatted formatted.txt --generate-tts --tts-voice adam

# List available voices
python generate_tts.py --list-voices
```

### Configure OpenAI GPT Automated Tagging
1. Set `OPENAI_API_KEY` environment variable (or configure via UI)
2. Login as admin: **Admin** > **System** > **Plugins**
3. Activate **"OpenAI API GPT integration"** under Asset Processing
4. Click **Options** to verify API key and select model (default: gpt-4o)
5. Configure metadata fields:
   - **Admin** > **System** > **Manage metadata fields**
   - Select target field (e.g., Keywords, Description)
   - Expand **Advanced** section
   - Set **GPT Prompt**: e.g., "List up to 10 keywords for this image"
   - Set **GPT Input Field**: `Image: Preview image` or another field
6. Process existing resources (optional):
   ```bash
   docker exec -it resourcespace bash
   cd /var/www/html/plugins/openai_gpt/pages
   php process_existing.php --field=FIELD_ID --limit=100
   ```

## Environment Variables

### Required (Both Local and Production)
- `DB_HOST`, `DB_USER`, `DB_PASS`, `DB_NAME`
- `RS_BASE_URL`, `RS_SCRAMBLE_KEY`
- `RS_EMAIL_FROM`, `RS_EMAIL_NOTIFY`

### Render-Specific Secrets
- `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` (mysql service)
- `BACKUP_DB_PASS`, `BACKUP_ENCRYPTION_KEY` (mysql-backup cron)
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID`, `R2_BUCKET` (mysql-backup cron)

**Auto-linked via `fromService` in render.yaml:**
- `DB_HOST`, `DB_PASS` (resourcespace ← mysql)
- `FACES_DB_HOST`, `FACES_DB_PASS` (faces ← mysql)

### Transcription Sync
- `RS_API_KEY` - Required for sync_transcription.py

### Document AI OCR
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to service account JSON key
- `DOCUMENTAI_PROJECT_ID` - GCP project ID
- `DOCUMENTAI_LOCATION` - Processor region (us or eu)
- `DOCUMENTAI_PROCESSOR_ID` - OCR processor ID

### ElevenLabs TTS
- `ELEVENLABS_API_KEY` - ElevenLabs API key for TTS generation

### OpenAI GPT (Automated Metadata Tagging)
- `OPENAI_API_KEY` - OpenAI API key for GPT metadata generation

## Testing Changes

### Dockerfile Changes
```bash
docker compose build resourcespace
docker compose up -d resourcespace
docker compose logs -f resourcespace
```

### Plugin Changes
Plugins are mounted read-only in docker-compose.yaml. Changes apply immediately on page refresh.

### Config Template Changes
Rebuild and restart:
```bash
docker compose down resourcespace
docker compose build resourcespace
docker compose up -d resourcespace
```

## Code Style

- PHP: ResourceSpace conventions (no specific linter configured)
- Python: Standard library only for sync_transcription.py
- Docker: Multi-stage builds where appropriate
- Shell: POSIX-compatible for scripts

## ResourceSpace API

Authentication uses SHA256 signing:
```
sign = sha256(api_key + query_string)
```

Key endpoints used:
- `get_resource_data` - Verify resource exists
- `get_resource_field_data` - Fetch field values
- `update_field` - Write single field
- `get_resource_type_fields` - List field definitions

## Backups

- Schedule: Daily at 03:00 UTC
- Compression: gzip
- Encryption: AES-256-CBC
- Storage: Cloudflare R2
- Retention: 30 days
