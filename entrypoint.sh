#!/bin/bash
set -e

# Generate config.php from environment variables
CONFIG_TEMPLATE="/docker/config.php.template"
CONFIG_TARGET="/var/www/html/include/config.php"

if [ -f "$CONFIG_TEMPLATE" ]; then
    echo "[entrypoint] Generating config.php from environment..."
    # Only substitute specific env vars (not PHP $variables)
    envsubst '${DB_HOST} ${DB_USER} ${DB_PASS} ${DB_NAME} ${RS_BASE_URL} ${RS_SCRAMBLE_KEY} ${RS_EMAIL_FROM} ${RS_EMAIL_NOTIFY}' < "$CONFIG_TEMPLATE" > "$CONFIG_TARGET"
    chmod 644 "$CONFIG_TARGET"
else
    echo "[entrypoint] ERROR: Config template not found at $CONFIG_TEMPLATE"
    exit 1
fi

# Validate critical env vars
if [ -z "$RS_SCRAMBLE_KEY" ]; then
    echo "[entrypoint] ERROR: RS_SCRAMBLE_KEY must be set"
    exit 1
fi

if [ -z "$DB_HOST" ]; then
    echo "[entrypoint] ERROR: DB_HOST must be set"
    exit 1
fi

echo "[entrypoint] Config generated successfully"

# Start cron service
service cron start

# Ensure daily cron jobs are executable
chmod +x /etc/cron.daily/*

# Start Apache in foreground
exec apachectl -D FOREGROUND
