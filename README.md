# ResourceSpace Docker

Docker-based deployment for ResourceSpace DAM with environment-driven configuration.

## Quick Start (Local Development)

1. **Copy environment template:**
   ```bash
   cp .env.example .env
   ```

2. **Generate a secure scramble key:**
   ```bash
   openssl rand -hex 32
   ```
   Add the generated key to your `.env` file as `RS_SCRAMBLE_KEY`.

3. **Build and start:**
   ```bash
   docker compose build
   docker compose up -d
   ```

4. **Access ResourceSpace:**
   - Application: http://localhost:8080
   - MinIO Console: http://localhost:9001 (admin: minioadmin/minioadmin)

## Configuration

All configuration is managed through environment variables. The `config.php` file is generated automatically at container startup from the template.

### Required Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_HOST` | Database hostname | `mariadb` |
| `DB_USER` | Database username | `resourcespace_rw` |
| `DB_PASS` | Database password | (secure value) |
| `DB_NAME` | Database name | `resourcespace` |
| `RS_BASE_URL` | Public URL | `http://localhost:8080` |
| `RS_SCRAMBLE_KEY` | File path encryption key | (generated) |
| `RS_EMAIL_FROM` | Sender email address | `noreply@example.com` |
| `RS_EMAIL_NOTIFY` | Admin notification email | `admin@example.com` |

### Critical Warning: scramble_key

**The `RS_SCRAMBLE_KEY` must NEVER be changed after files are uploaded.**

ResourceSpace uses this key to generate file storage paths. Changing it will make all existing files inaccessible. Store your production key securely in a backup location.

## Deployment to Render

The `render.yaml` blueprint deploys four services:

1. **MySQL Private Service** - Database with persistent storage
2. **ResourceSpace Web Service** - PHP application with filestore disk
3. **AI Faces Private Service** - InsightFace facial recognition
4. **MySQL Backup Cron Job** - Daily encrypted backups to Cloudflare R2

### Required Secrets

Set these in the Render dashboard before deployment:

| Secret | Purpose | Generation |
|--------|---------|------------|
| `MYSQL_ROOT_PASSWORD` | MySQL root access | `openssl rand -hex 32` |
| `MYSQL_PASSWORD` | Application DB password | `openssl rand -hex 32` |
| `DB_PASS` | Same as MYSQL_PASSWORD | (copy value) |
| `RS_SCRAMBLE_KEY` | File path encryption | `openssl rand -hex 32` |
| `RS_BASE_URL` | Your Render URL | `https://resourcespace-xxx.onrender.com` |
| `FACES_DB_PASS` | Faces service DB access | Same as MYSQL_PASSWORD |
| `BACKUP_DB_PASS` | Backup user password | `openssl rand -hex 32` |
| `BACKUP_ENCRYPTION_KEY` | Backup encryption | `openssl rand -hex 32` |
| `R2_ACCESS_KEY_ID` | Cloudflare R2 access | From Cloudflare dashboard |
| `R2_SECRET_ACCESS_KEY` | Cloudflare R2 secret | From Cloudflare dashboard |
| `R2_ACCOUNT_ID` | Cloudflare account ID | From Cloudflare dashboard |
| `R2_BUCKET` | R2 bucket name | Your bucket name |

### Post-Deployment Setup

1. Create backup user in MySQL:
   ```sql
   CREATE USER 'backup'@'%' IDENTIFIED BY '<BACKUP_DB_PASS>';
   GRANT SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER ON resourcespace.* TO 'backup'@'%';
   FLUSH PRIVILEGES;
   ```

2. Run ResourceSpace setup wizard at `/pages/setup.php`

3. Verify backup runs and uploads to R2

## Backup and Recovery

### Backup Schedule

Daily at 03:00 UTC. Backups are:
- Compressed with gzip
- Encrypted with AES-256-CBC
- Uploaded to Cloudflare R2
- Retained for 30 days

### Restore Procedure

1. **List available backups:**
   ```bash
   aws s3 ls s3://${R2_BUCKET}/backups/ \
       --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
   ```

2. **Download and decrypt:**
   ```bash
   aws s3 cp s3://${R2_BUCKET}/backups/resourcespace_YYYYMMDD_HHMMSS.sql.gz.enc ./
   openssl enc -aes-256-cbc -d -pbkdf2 \
       -in resourcespace_YYYYMMDD_HHMMSS.sql.gz.enc \
       -out backup.sql.gz \
       -pass env:BACKUP_ENCRYPTION_KEY
   gunzip backup.sql.gz
   ```

3. **Suspend ResourceSpace** in Render Dashboard

4. **Restore database:**
   ```bash
   mysql -h mysql -u root -p resourcespace < backup.sql
   ```

5. **Resume ResourceSpace** in Render Dashboard

6. **Verify** the `/login.php` health endpoint

**Recovery Time Objective (RTO):** ~30 minutes  
**Recovery Point Objective (RPO):** 24 hours

## Transcription Sync Tools

The `scripts/` folder contains tools for syncing OCR and transcription data to ResourceSpace following archival integrity rules.

### Setup

```bash
cd scripts
cp env.example .env
# Edit .env with RS_API_KEY
```

### Usage

```bash
# Full sync (all three layers)
python sync_transcription.py --resource-id 123 \
  --ocr ocr.txt --literal literal.txt --formatted formatted.txt \
  --lang de --version v1.2.0

# Check status
python sync_transcription.py --resource-id 123 --status

# List field IDs
python sync_transcription.py --list-fields
```

### Field Mutability Rules

| Layer | Rule |
|-------|------|
| OCR Text (Original) | **IMMUTABLE** - never overwrites |
| Transcription (Literal) | Write-once, `--force-literal` to update |
| Transcription (Formatted) | Iterable - updates when content changes |

See `scripts/ARCHIVAL_API_REFERENCE.md` for full API documentation.

## Project Structure

```
├── docker/
│   ├── backup/
│   │   ├── Dockerfile         # Backup job container
│   │   └── backup-mysql.sh    # Backup script with R2 upload
│   ├── faces/
│   │   └── Dockerfile         # InsightFace AI service
│   ├── mysql/
│   │   ├── Dockerfile         # MySQL 8 container
│   │   ├── my.cnf             # MySQL configuration
│   │   ├── healthcheck.sh     # Container health check
│   │   └── init.sql           # Database initialization
│   └── config.php.template    # Config template with env var placeholders
├── plugins/
│   └── ocr_sidepanel/         # Custom OCR display plugin
├── scripts/
│   ├── sync_transcription.py  # Archival transcription sync CLI
│   ├── ARCHIVAL_API_REFERENCE.md  # API documentation
│   └── env.example            # Environment template for scripts
├── .env.example               # Example environment variables (safe to commit)
├── .env                       # Actual environment variables (gitignored)
├── docker-compose.yaml        # Local development setup (MariaDB + MinIO)
├── Dockerfile                 # ResourceSpace container
├── entrypoint.sh              # Startup script (generates config)
└── render.yaml                # Render.com deployment config
```

## Local Development Stack

The local `docker-compose.yaml` includes:

- **resourcespace** - PHP application on port 8080
- **mariadb** - Database with health checks
- **minio** - S3-compatible object storage (ports 9000/9001)
- **minio-setup** - Creates initial bucket

## Installation Notes

- When setting up ResourceSpace, enter `mariadb` as the MySQL server (not `localhost`)
- Leave the "MySQL binary path" empty
- The container generates `config.php` automatically from environment variables

## Plugins

### OCR Side Panel

Displays OCR text alongside the resource image on the view page. Located in `plugins/ocr_sidepanel/`.
