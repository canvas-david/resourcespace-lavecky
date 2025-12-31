#!/bin/bash
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="resourcespace_${TIMESTAMP}.sql.gz.enc"
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

echo "[backup] Starting backup at $(date)"

# Dump database
echo "[backup] Dumping database..."
mysqldump \
    -h mysql \
    -u backup \
    -p"$BACKUP_DB_PASS" \
    --single-transaction \
    --routines \
    --triggers \
    --quick \
    resourcespace | gzip > "$TEMP_DIR/backup.sql.gz"

echo "[backup] Dump complete, size: $(du -h "$TEMP_DIR/backup.sql.gz" | cut -f1)"

# Encrypt with AES-256 (key from env)
echo "[backup] Encrypting backup..."
openssl enc -aes-256-cbc -salt -pbkdf2 \
    -in "$TEMP_DIR/backup.sql.gz" \
    -out "$TEMP_DIR/$BACKUP_FILE" \
    -pass env:BACKUP_ENCRYPTION_KEY

# Configure AWS CLI for R2
export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
R2_ENDPOINT="https://${R2_ACCOUNT_ID}.eu.r2.cloudflarestorage.com"

# Upload to R2 using AWS CLI (S3-compatible)
echo "[backup] Uploading to R2..."
aws s3 cp "$TEMP_DIR/$BACKUP_FILE" \
    "s3://${R2_BUCKET}/backups/$BACKUP_FILE" \
    --endpoint-url "$R2_ENDPOINT"

echo "[backup] Upload complete: $BACKUP_FILE"

# Prune backups older than 30 days
echo "[backup] Pruning old backups..."
CUTOFF_DATE=$(date -d "30 days ago" +%Y%m%d 2>/dev/null || date -v-30d +%Y%m%d)

aws s3 ls "s3://${R2_BUCKET}/backups/" \
    --endpoint-url "$R2_ENDPOINT" \
    | awk '{print $4}' \
    | grep -E '^resourcespace_[0-9]{8}_[0-9]{6}\.sql\.gz\.enc$' \
    | while read -r file; do
        file_date=$(echo "$file" | grep -oE '[0-9]{8}' | head -1)
        if [[ "$file_date" < "$CUTOFF_DATE" ]]; then
            echo "[backup] Removing old backup: $file"
            aws s3 rm "s3://${R2_BUCKET}/backups/$file" \
                --endpoint-url "$R2_ENDPOINT"
        fi
    done

echo "[backup] Backup complete at $(date)"
