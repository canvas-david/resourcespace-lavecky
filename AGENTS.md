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
| `Dockerfile` | Full ResourceSpace container (local dev) |
| `Dockerfile.render` | Lightweight Render build (uses GHCR base image) |
| `docker/base/Dockerfile` | Base image with apt packages + RS source |
| `docker-compose.yaml` | Local development stack |
| `render.yaml` | Render.com production deployment |
| `docker/config.php.template` | Config template with env var placeholders |
| `entrypoint.sh` | Generates config.php, auto-inits DB, creates admin user |
| `docker/mysql/` | MySQL container for Render |
| `docker/backup/` | Backup cron job with R2 upload |
| `docker/faces/` | InsightFace AI service |
| `plugins/tts_audio/` | ElevenLabs TTS audio generation plugin |
| `plugins/tts_audio/pages/generate.php` | TTS generation endpoint (calls ElevenLabs API) |
| `plugins/tts_audio/hooks/view.php` | Audio player panel on resource view |
| `scripts/db.sh` | Render MySQL helper (SSH database access) |
| `scripts/create_ocr_fields.sql` | OCR/transcription field schema |
| `scripts/process_ocr.py` | Google Document AI OCR processor |
| `scripts/ocr_google_vision.py` | Google Cloud Vision OCR (simpler, uses API key) |
| `scripts/translate_ocr.py` | Claude Opus 4.5 translation (Anthropic API) |
| `scripts/process_yadvashem_batch.py` | Batch OCR + translation pipeline |
| `scripts/upload_testimony.py` | Upload processed documents to ResourceSpace |
| `scripts/sync_transcription.py` | Archival transcription sync CLI |
| `scripts/generate_tts.py` | ElevenLabs TTS audio generator |
| `.github/workflows/build-base.yml` | GitHub Actions to build/push base image |

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
| English Translation | Iterable, `--force-translation` to update |
| Review Status | Never downgrades from `reviewed`/`approved` |

### Metadata Tab Structure
Fields are organized into tabs for different user workflows:

| Tab | Purpose | Fields |
|-----|---------|--------|
| 1. Default | Standard asset metadata | Date, Filename, Keywords, etc. |
| 2. Transcription | Readable content | Literal Transcription, Reader-Friendly Version, English Translation |
| 3. Review | Editorial workflow | Transcription Status, Notes, Formatting Status, Notes |
| 4. Technical | Processing details | OCR Status, Engine, Language, Methods, Pipeline Version |
| 5. Archival | Raw source data | Original OCR Output |

Tab names are prefixed with numbers to force correct sort order (ResourceSpace sorts alphabetically).

**Database schema:** The `resource_type_field.tab` column is an integer FK to `tab.ref`, not a string. Create tabs first, then reference by ID:
```sql
-- Create tab
INSERT INTO tab (ref, name, order_by) VALUES (2, '2. Transcription', 20);
-- Assign field to tab
UPDATE resource_type_field SET tab = 2 WHERE ref = 89;
```

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
1. **First time only:** Build and push base image (see "Rebuild Base Image" below)
2. Configure GHCR credentials in Render dashboard:
   - Go to resourcespace service → Settings → Docker Credentials
   - Registry: `ghcr.io`
   - Username: your GitHub username
   - Password: GitHub PAT with `read:packages` scope
3. Set secrets in Render dashboard (see README.md):
   - `MYSQL_ROOT_PASSWORD`, `MYSQL_PASSWORD` on mysql service
   - `RS_SCRAMBLE_KEY`, `RS_BASE_URL`, `RS_EMAIL_*` on resourcespace service
4. Push to trigger auto-deploy (~10-20 seconds with base image)
5. Database auto-initializes on first run (no setup wizard needed)
6. Login with `admin` / `admin` and change password immediately
7. Create backup user in MySQL for backups
8. Configure AI Faces plugin URL: `http://faces:8001`

### Rebuild Base Image
The base image contains apt packages and ResourceSpace source. Rebuild when:
- Upgrading ResourceSpace version
- Adding/removing system packages
- Changing PHP configuration

**Option 1: GitHub Actions (recommended)**
```bash
# Manual trigger via GitHub UI or CLI
gh workflow run build-base.yml -f version=10.7
```

**Option 2: Local build**
```bash
# Build and push manually
docker build -t ghcr.io/canvas-david/resourcespace-base:10.7 -f docker/base/Dockerfile .
docker push ghcr.io/canvas-david/resourcespace-base:10.7
```

The base image is private. Render pulls it using configured Docker credentials.

### Process OCR

**Option 1: Google Cloud Vision API (Recommended)**
Simpler setup, uses API key instead of service account credentials.

```bash
cd scripts
# OCR with language hint
GOOGLE_API_KEY="your-key" python ocr_google_vision.py \
  --file document.jpg --lang pl --output ocr.txt

# JSON output with confidence score
GOOGLE_API_KEY="your-key" python ocr_google_vision.py \
  --file document.jpg --lang he --json
```

**Option 2: Google Document AI**
More complex setup (service account), but offers additional features like form/table extraction.

```bash
cd scripts
# Process and sync to ResourceSpace
python process_ocr.py --file document.pdf --resource-id 123 --lang de

# Output to file only
python process_ocr.py --file document.pdf --output ocr.txt
```

**OCR Quality Comparison:**
| Factor | Google Vision/Document AI | Claude Vision (LLM) |
|--------|--------------------------|---------------------|
| Accuracy | 98-99% on typewritten | ~95-97% variable |
| Hallucination Risk | Near zero | Can fabricate text |
| Confidence Scores | Yes, per-block | No |
| Use for Archival | ✓ Recommended | ⚠ Not recommended |

For archival/Holocaust testimony work, always use dedicated OCR (Google Vision or Document AI) to avoid LLM hallucination risks.

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

**Docker container requirements** (already configured in Dockerfile):
- `openssh-server` package installed
- `~/.ssh` directory with `chmod 0700` permissions
- See [render.com/docs/ssh#docker-specific-configuration](https://render.com/docs/ssh#docker-specific-configuration)

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
./db.sh "SELECT ref, name, title, tab FROM resource_type_field WHERE ref BETWEEN 88 AND 102"

# Check resource field data
./db.sh "SELECT * FROM resource_data WHERE resource = 123"

# Update field order
./db.sh "UPDATE resource_type_field SET order_by = 10 WHERE ref = 89"

# Link resources as related
./db.sh "INSERT IGNORE INTO resource_related (resource, related) VALUES (6, 7), (7, 6)"
```

**Creating new metadata fields:**
Fields must be linked to resource types via the join table, or API `update_field` will silently fail.

```bash
# 1. Create the field
./db.sh "INSERT INTO resource_type_field (ref, name, title, type, tab, global, active) 
  VALUES (101, 'englishtranslation', 'English Translation', 5, 2, 1, 1)"

# 2. Link to resource types (CRITICAL - without this, API updates fail)
./db.sh "INSERT IGNORE INTO resource_type_field_resource_type 
  (resource_type_field, resource_type) VALUES 
  (101, 0), (101, 1), (101, 2), (101, 3), (101, 4)"

# Verify field is linked
./db.sh "SELECT * FROM resource_type_field_resource_type WHERE resource_type_field = 101"
```

**SSH Rate Limiting:**
Render SSH connections are rate-limited. Space out multiple queries:
```bash
# Add delays between commands
./db.sh "query1" && sleep 5 && ./db.sh "query2"
```

**SSH Host Key Setup:**
To avoid host key warnings, add Render's official key to known_hosts:
```bash
# Oregon region
echo "ssh.oregon.render.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFON8eay2FgHDBIVOLxWn/AWnsDJhCVvlY1igWEFoLD2" >> ~/.ssh/known_hosts
```

Other regions: [render.com/docs/ssh](https://render.com/docs/ssh#renders-public-key-fingerprints)

### Translate OCR Text (Claude Opus 4.5)
```bash
cd scripts
# Translate Polish OCR to English (uses Opus 4.5 by default)
python translate_ocr.py --input ocr_pl.txt --source pl --output translated.txt

# Translate Hebrew with faster/cheaper Sonnet model
python translate_ocr.py --input ocr_he.txt --source he --model sonnet --output out.txt

# Batch process Yad Vashem documents (OCR + Translation)
python process_yadvashem_batch.py \
  --input-dir downloads/yadvashem_3555547 \
  --polish-pages 1-20 \
  --hebrew-pages 21-34

# Dry run to preview batch processing
python process_yadvashem_batch.py \
  --input-dir downloads/yadvashem_3555547 \
  --polish-pages 1-20 \
  --hebrew-pages 21-34 \
  --dry-run
```

### Upload Processed Documents to ResourceSpace
```bash
cd scripts
# Upload Polish testimony (creates resource, populates OCR/translation fields)
RS_BASE_URL="https://your-instance.onrender.com" \
RS_API_KEY="your-api-key" \
python upload_testimony.py --resource-dir downloads/doc_123/resource_polish

# Upload Hebrew translation linked to Polish resource (ID 6)
RS_BASE_URL="https://your-instance.onrender.com" \
RS_API_KEY="your-api-key" \
python upload_testimony.py --resource-dir downloads/doc_123/resource_hebrew --related-to 6
```

**Expected directory structure:**
```
resource_polish/
├── metadata.json          # Title, description, keywords
├── ocr_combined.txt       # Combined OCR text
├── translation_combined.txt  # Combined English translation
└── page_01.jpg - page_XX.jpg  # Page images
```

Note: Images must still be uploaded manually via UI (API file upload requires server-side path configuration).

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

### Google Cloud OCR

**Vision API (simpler):**
- `GOOGLE_API_KEY` - Google Cloud API key (enable Vision API in console)

**Document AI (advanced):**
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to service account JSON key
- `DOCUMENTAI_PROJECT_ID` - GCP project ID
- `DOCUMENTAI_LOCATION` - Processor region (us or eu)
- `DOCUMENTAI_PROCESSOR_ID` - OCR processor ID

### Claude Translation (Anthropic)
- `ANTHROPIC_API_KEY` - Anthropic API key for Claude Opus 4.5 translation

### ElevenLabs TTS
- `ELEVENLABS_API_KEY` - ElevenLabs API key for TTS generation (set in Render dashboard)

### OpenAI GPT (Automated Metadata Tagging)
- `OPENAI_API_KEY` - OpenAI API key for GPT metadata generation

## Testing Changes

### Dockerfile Changes (Local)
```bash
# Local development uses full Dockerfile
docker compose build resourcespace
docker compose up -d resourcespace
docker compose logs -f resourcespace
```

### Dockerfile.render Changes
```bash
# Test the Render build locally (requires base image)
docker build -t resourcespace-test -f Dockerfile.render .
docker run --rm -p 8080:80 resourcespace-test
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
- `create_resource` - Create new resource (returns resource ID)
- `get_resource_data` - Verify resource exists
- `get_resource_field_data` - Fetch field values
- `update_field` - Write single field (returns `false` if field not linked to resource type!)
- `get_resource_type_fields` - List field definitions
- `add_alternative_file` - Create alt file record (DB only, no file copy)
- `get_alternative_files` - List alternative files for a resource
- `do_search` - Search resources

**Linking related resources** (no direct API, use database):
```sql
INSERT IGNORE INTO resource_related (resource, related) VALUES (6, 7), (7, 6);
```

## Plugin Development

### Plugin YAML Format
The plugin YAML must follow ResourceSpace conventions:

```yaml
name: my_plugin          # Must match folder name (lowercase, no spaces)
title: My Plugin         # Display name in admin
author: Your Name
version: 1.0.0
desc: Plugin description  # NOT 'description'
icon: fa fa-icon-name
category: AI             # Category string, not number
config_url: /plugins/my_plugin/pages/setup.php
disable_group_select: 0
```

**Common mistakes:**
- Using `description` instead of `desc`
- Using `name` for display (use `title`)
- Setting `category` as a number instead of string

### Hook Naming Convention
```php
// Format: Hook{Pluginname}{Page}{Hookpoint}
function HookMy_pluginViewCustompanels() { ... }
function HookMy_pluginAllInitialise() { ... }
```

### Adding Panels to Resource View
Use the `Custompanels` hook with `RecordBox`/`RecordPanel` structure:

```php
function HookMy_pluginViewCustompanels() {
    global $ref, $baseurl;
    ?>
    <div class="RecordBox">
        <div class="RecordPanel">
            <div class="Title">
                <i class="fa fa-icon"></i>&nbsp;Panel Title
            </div>
            <!-- Panel content -->
        </div>
    </div>
    <?php
    return false; // Allow other panels
}
```

### PHP Function Gotchas

**get_config_option()** - Third parameter is by reference:
```php
// WRONG - can't pass string literal by reference
$value = get_config_option(null, 'option_name', 'default');

// CORRECT
$value = 'default';
get_config_option([], 'option_name', $value, 'default');
```

**CSRF Tokens** - Required for POST requests:
```php
// In PHP: Generate token
$csrf_token = generateCSRFToken($usersession, 'form_id');

// In JavaScript: Include in AJAX
var params = 'data=value&CSRFToken=' + csrfToken;
```

### Alternative File Upload
`add_alternative_file()` only creates the database record. You must manually copy the file:

```php
// 1. Create DB record
$alt_ref = add_alternative_file($ref, 'Name', 'Description', 'file.mp3', 'mp3', $size, '');

// 2. Get target path (includes scramble key)
$target_path = get_resource_path($ref, true, "", true, "mp3", -1, 1, false, "", $alt_ref);

// 3. Copy file to filestore
copy($temp_file, $target_path);
chmod($target_path, 0664);
```

**File path format:** `{ref}_alt_{alt_ref}_{scramble}.{ext}`

### Audio/Video URL for Inline Playback
Use `noattach=true` for streaming instead of download:
```php
$url = $baseurl . '/pages/download.php?ref=' . $ref . '&ext=mp3&alternative=' . $alt_ref . '&noattach=true&k=';
```

### Environment Variables in Apache/PHP
Container environment variables aren't automatically available to Apache. Export them in `entrypoint.sh`:

```bash
# Add to /etc/apache2/envvars for PHP access via getenv()
if [ -n "$MY_API_KEY" ]; then
    echo "export MY_API_KEY='$MY_API_KEY'" >> /etc/apache2/envvars
fi
```

### Disabling Plugins via Database
```sql
-- Remove plugin from active plugins
DELETE FROM plugins WHERE name='plugin_name';
```

## Backups

- Schedule: Daily at 03:00 UTC
- Compression: gzip
- Encryption: AES-256-CBC
- Storage: Cloudflare R2
- Retention: 30 days
