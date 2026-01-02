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
| `cronjob` | Cron schedule for background tasks |
| `docker/mysql/` | MySQL container for Render |
| `docker/backup/` | Backup cron job with R2 upload |
| `docker/faces/` | InsightFace AI service |
| `plugins/tts_audio/` | ElevenLabs TTS audio generation plugin |
| `plugins/tts_audio/pages/generate.php` | TTS generation endpoint (calls ElevenLabs API) |
| `plugins/tts_audio/hooks/view.php` | Audio player panel on resource view |
| `scripts/db.sh` | Render MySQL helper (SSH database access) |
| `scripts/db/create_ocr_fields.sql` | OCR/transcription field schema (fields 88-102) |
| `scripts/db/create_tts_fields.sql` | TTS metadata field schema (fields 103-106) |
| `scripts/db/setup_ocr_fields.sh` | OCR field setup automation helper |
| `scripts/ocr.py` | **Unified OCR with auto-detection** (handwriting → Document AI) |
| `scripts/legacy/process_ocr.py` | Google Document AI OCR processor (legacy) |
| `scripts/legacy/ocr_google_vision.py` | Google Cloud Vision OCR (legacy) |
| `scripts/legacy/ocr_claude.py` | Claude Vision OCR (⚠️ LLM - not for archival) |
| `scripts/translate_ocr.py` | Claude Opus 4.5 translation (Anthropic API) |
| `scripts/transcribe_ocr.py` | **OCR-to-literal transcription** (archival correction) |
| `scripts/ocr_verify.py` | **4-model OCR verification** (consensus voting) |
| `scripts/docs/OCR_HANDLING_RULES.md` | Archival rules for OCR text processing |
| `scripts/batch_ocr.py` | Batch OCR + translation pipeline (auto-detects handwriting) |
| `scripts/upload/upload_testimony.py` | Upload processed documents to ResourceSpace |
| `scripts/sync_transcription.py` | Archival transcription sync CLI |
| `scripts/generate_tts.py` | ElevenLabs TTS audio generator |
| `scripts/faces/detect_faces.php` | PHP face detection helper |
| `scripts/faces/test_faces.sh` | Face AI service testing |
| `scripts/docs/ARCHIVAL_API_REFERENCE.md` | Detailed API reference for transcription sync |
| `.github/workflows/build-base.yml` | GitHub Actions to build/push base image |
| `downloads/` | Working directory for batch document processing |

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

| ID | Field | Rule |
|----|-------|------|
| 88 | OCR Text (Original) | **IMMUTABLE** - never overwrite |
| 89 | Transcription (Literal) | Write-once, `--force-literal` to update |
| 96 | Transcription (Formatted) | Iterable - updates allowed |
| 101 | English Translation | Iterable, `--force-translation` to update |
| 94, 98 | Review Status | Never downgrades from `reviewed`/`approved` |

**Full field reference:** See `scripts/docs/ARCHIVAL_API_REFERENCE.md` for complete field IDs (88-102) and API documentation.

### OCR Processing Workflow

**CRITICAL: Follow proper archival workflow for OCR text.**

```
Raw OCR (88) → Literal (89) → Formatted (96)
     ↑              ↑              ↑
  Machine      Human-verified   Reader-friendly
  IMMUTABLE    Write-once       Iterable
```

| Step | Field | Process | Rules |
|------|-------|---------|-------|
| 1. OCR | 88 | `ocr.py` outputs raw text | Never modify after save |
| 2. Literal | 89 | `transcribe_ocr.py` corrects OCR | Correct machine errors ONLY |
| 3. Format | 96 | Add headers, structure | Based on Field 89, not Field 88 |

**Using transcribe_ocr.py:**
```bash
# With image verification (best accuracy)
ANTHROPIC_API_KEY="key" python scripts/transcribe_ocr.py \
    --ocr raw_ocr.txt --scan original.jpg --output literal.txt

# Without image (OCR-only, less accurate)
ANTHROPIC_API_KEY="key" python scripts/transcribe_ocr.py \
    --ocr raw_ocr.txt --output literal.txt
```

**Rules for Literal Transcription (Field 89):**
- ✓ Correct OCR machine errors (misread characters)
- ✓ Mark unclear text: `[unclear]`, `[illegible]`, `[word?]`
- ✗ Do NOT "fix" author's spelling, grammar, or style
- ✗ Do NOT modernize language
- ✗ Do NOT add interpretations

**Full rules:** See `scripts/docs/OCR_HANDLING_RULES.md`

### Multi-Model OCR Verification

For high-confidence OCR, use `ocr_verify.py` to run 4 models and build consensus:

| Model | Type | Strength |
|-------|------|----------|
| Document AI | Dedicated OCR | Best handwriting accuracy |
| Vision API | Dedicated OCR | Fast, good for typewritten |
| Claude Vision | LLM | Semantic understanding |
| GPT-5.2 Vision | LLM | Semantic understanding |

**Consensus Logic:**
- 4/4 agree: Very high confidence (~99%+ accuracy)
- 3/4 agree: High confidence (~95%+ accuracy)
- 2/4 agree: Medium confidence - flag for review
- All differ: Low confidence - human required

**Usage:**
```bash
# Full 4-model verification
source scripts/.env
ANTHROPIC_API_KEY="key" OPENAI_API_KEY="key" \
python scripts/ocr_verify.py --image page.jpg --output consensus.txt --report report.json

# Batch processing
python scripts/ocr_verify.py --input-dir scans/ --output-dir verified/ --report-dir reports/

# Cheaper: Only dedicated OCR engines
python scripts/ocr_verify.py --image page.jpg --engines docai,vision --output out.txt
```

**Cost:** ~$0.03-0.05 per page (all 4 models)

### Metadata Tab Structure
Fields are organized into tabs for different user workflows. Tab names are prefixed with numbers to force correct sort order (ResourceSpace sorts alphabetically):

| Tab Name | Purpose | Field IDs |
|----------|---------|-----------|
| 1. Default | Standard asset metadata | (built-in) |
| 2. Transcription | Readable content (full-width text) | 89, 96, 101 |
| 3. Review | Editorial workflow | 94, 95, 98, 99 |
| 4. Technical | Processing details + source language | 90, 91, 92, 93, 97, 100, 102 |
| 5. Archival | Raw source data | 88 |

**Note:** Tabs only display if they contain fields with values. Empty tabs are hidden.

**Complete field schema:** Run `scripts/db/create_ocr_fields.sql` to create all transcription fields (88-102).

### Field ID Quick Reference

| ID | Name | Tab | Purpose |
|----|------|-----|---------|
| 88 | `ocrtext` | Archival | Raw OCR output (IMMUTABLE) |
| 89 | `transcriptioncleaned` | Transcription | Literal transcription |
| 90 | `ocrengine` | Technical | OCR engine used |
| 91 | `ocrlanguagedetected` | Technical | Detected language |
| 92 | `ocrstatus` | Technical | Processing status |
| 93 | `transcriptionmethod` | Technical | AI method used |
| 94 | `transcriptionreviewstatus` | Review | Review status |
| 95 | `transcriptionnotes` | Review | Transcription notes |
| 96 | `transcriptionreaderformatted` | Transcription | Reader-friendly version |
| 97 | `formattingmethod` | Technical | Formatting method |
| 98 | `formattingreviewstatus` | Review | Formatting review status |
| 99 | `formattingnotes` | Review | Formatting notes |
| 100 | `processingversion` | Technical | Pipeline version |
| 101 | `englishtranslation` | Transcription | English translation |
| 102 | `translationsourcelanguage` | Transcription | Source language code |
| 103 | `ttsstatus` | Transcription | TTS generation status |
| 104 | `ttsengine` | Transcription | TTS engine |
| 105 | `ttsvoice` | Transcription | TTS voice used |
| 106 | `ttsgeneratedat` | Transcription | TTS timestamp |

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

**Unified OCR Script (Recommended)**
The `ocr.py` script auto-detects handwritten vs typewritten content and routes to the optimal engine:
- **Handwritten content** → Document AI (better accuracy on cursive, historical scripts)
- **Typewritten content** → Vision API (faster, simpler setup)

```bash
cd scripts
# Auto-detect and use best engine
python ocr.py --file letter.jpg --lang pl --output ocr.txt

# Force Document AI for known handwritten content
python ocr.py --file handwritten_letter.jpg --engine documentai --output ocr.txt

# Force Vision API for typewritten documents
python ocr.py --file typed_doc.jpg --engine vision --output ocr.txt

# JSON output with metadata (includes engine used, confidence, handwriting ratio)
python ocr.py --file letter.jpg --json
```

**Setting Up Document AI (Required for Handwriting)**

1. **Enable API**: Go to [GCP Console](https://console.cloud.google.com/apis/library/documentai.googleapis.com) and enable Document AI API

2. **Create Processor**:
   - Navigate to Document AI → Processors → Create Processor
   - Select "Document OCR" (general purpose)
   - Region: `us` or `eu` (note this for `DOCUMENTAI_LOCATION`)
   - Copy the processor ID from the details page

3. **Create Service Account**:
   - Go to IAM & Admin → Service Accounts → Create Service Account
   - Name: `documentai-ocr`
   - Grant role: `roles/documentai.apiUser`
   - Create JSON key and download

4. **Set Environment Variables**:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
   export DOCUMENTAI_PROJECT_ID="your-gcp-project-id"
   export DOCUMENTAI_LOCATION="us"  # or "eu"
   export DOCUMENTAI_PROCESSOR_ID="abc123def456"
   ```

**Vision API Only (Simpler Setup)**
If you only need typewritten document OCR, Vision API with an API key is sufficient:

```bash
cd scripts
GOOGLE_API_KEY="your-key" python ocr.py --file document.jpg --engine vision --output ocr.txt
```

**Legacy Scripts (Still Available)**
- `ocr_google_vision.py` - Direct Vision API access
- `process_ocr.py` - Direct Document AI access with ResourceSpace sync
- `ocr_claude.py` - Claude Vision OCR (⚠️ NOT for archival work)

**OCR Engine Comparison:**
| Factor | Vision API | Document AI | Claude Vision (LLM) |
|--------|------------|-------------|---------------------|
| Best For | Typewritten docs | Handwriting, forms | Quick experiments |
| Accuracy (typed) | 98-99% | 98-99% | ~95-97% |
| Accuracy (handwritten) | 70-85% | 90-95% | ~85-90% |
| Hallucination Risk | Near zero | Near zero | Can fabricate text |
| Setup Complexity | API key only | Service account | API key |
| Cost | ~$0.0015/image | ~$0.01/page | ~$0.01/image |
| Use for Archival | ✓ Typewritten | ✓ Handwritten | ⚠ Not recommended |

**⚠️ For archival/Holocaust testimony work, always use dedicated OCR (Vision or Document AI) to avoid LLM hallucination risks.**

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
# 1. Create the field (example: custom field 110)
./db.sh "INSERT INTO resource_type_field (ref, name, title, type, tab, global, active) 
  VALUES (110, 'customfield', 'Custom Field', 5, 2, 1, 1)"

# 2. Link to resource types (CRITICAL - without this, API updates fail)
./db.sh "INSERT IGNORE INTO resource_type_field_resource_type 
  (resource_type_field, resource_type) VALUES 
  (110, 0), (110, 1), (110, 2), (110, 3), (110, 4)"

# Verify field is linked
./db.sh "SELECT * FROM resource_type_field_resource_type WHERE resource_type_field = 110"
```

**Pre-defined field schemas:** Use `create_ocr_fields.sql` (88-102) and `create_tts_fields.sql` (103-106) instead of manual creation.

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

# Batch process Yad Vashem documents (auto-detects handwriting)
python batch_ocr.py \
  --input-dir downloads/yadvashem_3555547 \
  --polish-pages 1-20 \
  --hebrew-pages 21-34

# Force Document AI for known handwritten letters
python batch_ocr.py \
  --input-dir downloads/handwritten_letters \
  --polish-pages 1-10 \
  --ocr-engine documentai

# Dry run to preview batch processing
python batch_ocr.py \
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

The unified `ocr.py` script uses these credentials for auto-detection and routing:

**Vision API (typewritten docs, auto-detection):**
- `GOOGLE_API_KEY` - Google Cloud API key (enable Vision API in console)

**Document AI (handwritten content):**
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to service account JSON key
- `DOCUMENTAI_PROJECT_ID` - GCP project ID
- `DOCUMENTAI_LOCATION` - Processor region (us or eu)
- `DOCUMENTAI_PROCESSOR_ID` - OCR processor ID

**Note:** For auto-detection, both Vision API key and Document AI credentials should be set. The script uses Vision API to detect handwriting ratio, then routes to Document AI if >30% handwriting is detected.

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

## Batch Document Processing (downloads/)

The `downloads/` directory is the working area for batch OCR and translation workflows.

### Directory Structure
```
downloads/
└── yadvashem_3555547/           # Document ID from source archive
    ├── metadata.json            # Source metadata
    ├── download_images.sh       # Script to fetch page images
    ├── README.md                # Document description
    ├── ocr/                     # Raw OCR output per page
    │   ├── page_01_pl.txt       # {page}_{language}.txt
    │   └── page_21_he.txt
    ├── translations/            # English translations per page
    │   ├── page_01_pl_en.txt    # {page}_{source}_en.txt
    │   └── page_21_he_en.txt
    ├── resource_polish/         # Upload-ready bundle (Polish pages)
    │   ├── metadata.json
    │   ├── ocr_combined.txt
    │   └── translation_combined.txt
    └── resource_hebrew/         # Upload-ready bundle (Hebrew pages)
        ├── metadata.json
        ├── ocr_combined.txt
        └── translation_combined.txt
```

### Batch Processing Workflow
```bash
cd scripts

# 1. Process OCR + translation for multi-language document
# (auto-detects handwriting and routes to best OCR engine)
python batch_ocr.py \
  --input-dir ../downloads/yadvashem_3555547 \
  --polish-pages 1-20 \
  --hebrew-pages 21-34

# For known handwritten content, force Document AI:
python batch_ocr.py \
  --input-dir ../downloads/yadvashem_3555547 \
  --polish-pages 1-20 \
  --hebrew-pages 21-34 \
  --ocr-engine documentai

# 2. Upload Polish testimony to ResourceSpace
RS_BASE_URL="https://your-instance.onrender.com" \
RS_API_KEY="your-api-key" \
python upload_testimony.py --resource-dir ../downloads/yadvashem_3555547/resource_polish

# 3. Upload Hebrew testimony, linked to Polish resource (ID 6)
python upload_testimony.py \
  --resource-dir ../downloads/yadvashem_3555547/resource_hebrew \
  --related-to 6
```

### Naming Conventions
- **Page files:** `page_NN_{lang}.txt` where NN is zero-padded page number
- **Translations:** `page_NN_{source}_en.txt` (English output from source language)
- **Combined files:** `ocr_combined.txt`, `translation_combined.txt`

---

## Troubleshooting

### API update_field Returns False
**Symptom:** `update_field` API call returns `false` but no error.

**Cause:** Field not linked to resource type in join table.

**Fix:**
```bash
./db.sh "INSERT IGNORE INTO resource_type_field_resource_type 
  (resource_type_field, resource_type) VALUES 
  (FIELD_ID, 0), (FIELD_ID, 1), (FIELD_ID, 2), (FIELD_ID, 3), (FIELD_ID, 4)"
```

### SSH Connection Rate Limited
**Symptom:** `Connection refused` after multiple SSH commands.

**Cause:** Render rate-limits SSH connections.

**Fix:** Add delays between commands:
```bash
./db.sh "query1" && sleep 5 && ./db.sh "query2"
```

### Files Inaccessible After Config Change
**Symptom:** Uploaded files return 404 or blank.

**Cause:** `RS_SCRAMBLE_KEY` was changed.

**Fix:** Restore original key from backup. **There is no recovery if key is lost.**

### Plugin Not Appearing in Admin
**Symptom:** Plugin folder exists but not listed in Plugins page.

**Cause:** Invalid YAML syntax or wrong field names.

**Check:**
- Use `desc:` not `description:`
- Use `title:` for display name, `name:` must match folder
- `category:` must be string not number

### TTS Generation Fails
**Symptom:** Generate button does nothing or returns error.

**Check:**
1. `ELEVENLABS_API_KEY` exported in `/etc/apache2/envvars`
2. Formatted transcription field (96) has content
3. Browser console for JavaScript errors

### OCR Returns Empty Text
**Symptom:** Google Vision/Document AI returns blank.

**Causes:**
- Image too small or low quality
- Wrong MIME type detected
- API quota exceeded

**Debug:**
```bash
# Check with JSON output for error details
GOOGLE_API_KEY="key" python ocr_google_vision.py --file image.jpg --json
```

---

## Backups

- Schedule: Daily at 03:00 UTC
- Compression: gzip
- Encryption: AES-256-CBC
- Storage: Cloudflare R2
- Retention: 30 days
