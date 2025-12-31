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
| `entrypoint.sh` | Generates config.php at runtime |
| `docker/mysql/` | MySQL container for Render |
| `docker/backup/` | Backup cron job with R2 upload |
| `docker/faces/` | InsightFace AI service |
| `plugins/ocr_sidepanel/` | OCR display plugin |
| `scripts/sync_transcription.py` | Archival transcription sync CLI |

## Critical Rules

### scramble_key
**NEVER change `RS_SCRAMBLE_KEY` after files are uploaded.** This key generates file storage paths. Changing it makes all existing files inaccessible.

### Transcription Field Mutability
The sync_transcription.py enforces archival integrity:

| Field | Rule |
|-------|------|
| OCR Text (Original) | **IMMUTABLE** - never overwrite |
| Transcription (Literal) | Write-once, `--force-literal` to update |
| Transcription (Formatted) | Iterable - updates allowed |
| Review Status | Never downgrades from `reviewed`/`approved` |

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
1. Set secrets in Render dashboard (see README.md)
2. Push to trigger auto-deploy
3. Create backup user in MySQL
4. Run setup wizard at `/pages/setup.php`

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

## Environment Variables

### Required (Both Local and Production)
- `DB_HOST`, `DB_USER`, `DB_PASS`, `DB_NAME`
- `RS_BASE_URL`, `RS_SCRAMBLE_KEY`
- `RS_EMAIL_FROM`, `RS_EMAIL_NOTIFY`

### Render-Specific Secrets
- `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD`
- `BACKUP_DB_PASS`, `BACKUP_ENCRYPTION_KEY`
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID`, `R2_BUCKET`
- `FACES_DB_PASS`

### Transcription Sync
- `RS_API_KEY` - Required for sync_transcription.py

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
