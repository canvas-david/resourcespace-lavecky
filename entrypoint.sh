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

# Wait for MySQL to be ready
echo "[entrypoint] Waiting for MySQL at $DB_HOST..."
echo "[entrypoint] DB_USER=$DB_USER, DB_NAME=$DB_NAME, DB_PASS length=${#DB_PASS}"
MAX_RETRIES=30
RETRY_COUNT=0
while ! mysql -h"$DB_HOST" -u"$DB_USER" -p"$DB_PASS" -e "SELECT 1" "$DB_NAME" 2>&1; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "[entrypoint] ERROR: MySQL not ready after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "[entrypoint] MySQL not ready, waiting... ($RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done
echo "[entrypoint] MySQL is ready"

# Check if database is initialized (check for 'user' table)
TABLE_EXISTS=$(mysql -h"$DB_HOST" -u"$DB_USER" -p"$DB_PASS" -N -e "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='$DB_NAME' AND table_name='user';" 2>/dev/null || echo "0")

if [ "$TABLE_EXISTS" = "0" ]; then
    echo "[entrypoint] Database not initialized. Running schema setup..."
    
    # ResourceSpace includes dbstruct SQL files in its distribution
    # Run the main database structure file
    if [ -f "/var/www/html/dbstruct/dbstruct.txt" ]; then
        echo "[entrypoint] Loading database schema from dbstruct.txt..."
        mysql -h"$DB_HOST" -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" < /var/www/html/dbstruct/dbstruct.txt
        echo "[entrypoint] Database schema loaded"
    else
        echo "[entrypoint] WARNING: dbstruct.txt not found, attempting PHP-based init..."
        # Fallback: Use PHP CLI to run database setup
        cd /var/www/html
        php -r "
            \$mysql_server = '${DB_HOST}';
            \$mysql_username = '${DB_USER}';
            \$mysql_password = '${DB_PASS}';
            \$mysql_db = '${DB_NAME}';
            include 'include/db.php';
            if (file_exists('dbstruct/dbstruct.txt')) {
                \$sql = file_get_contents('dbstruct/dbstruct.txt');
                sql_query(\$sql);
                echo 'Database schema loaded via PHP';
            }
        " 2>/dev/null || echo "[entrypoint] PHP init skipped"
    fi
    
    # Create default admin user with MD5 password hash
    echo "[entrypoint] Creating default admin user..."
    mysql -h"$DB_HOST" -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "
        INSERT INTO user (username, password, fullname, email, usergroup, created, approved)
        VALUES ('admin', MD5('admin'), 'Administrator', '${RS_EMAIL_NOTIFY:-admin@localhost}', 3, NOW(), 1)
        ON DUPLICATE KEY UPDATE password=MD5('admin');
    " 2>/dev/null && echo "[entrypoint] Admin user created" || echo "[entrypoint] Admin user may exist"
    
    echo "[entrypoint] Database initialization complete"
    echo "[entrypoint] ⚠️  DEFAULT LOGIN: admin / admin - CHANGE PASSWORD IMMEDIATELY"
else
    echo "[entrypoint] Database already initialized (user table exists)"
fi

# Always ensure admin user exists with known password
# ResourceSpace uses MySQL's PASSWORD() function for hashing
echo "[entrypoint] Ensuring admin user exists with default password..."
mysql -h"$DB_HOST" -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "
    INSERT INTO user (username, password, fullname, email, usergroup, created, approved)
    VALUES ('admin', MD5('admin'), 'Administrator', '${RS_EMAIL_NOTIFY:-admin@localhost}', 3, NOW(), 1)
    ON DUPLICATE KEY UPDATE password=MD5('admin');
" 2>/dev/null && echo "[entrypoint] Admin user ready (admin/admin)" || echo "[entrypoint] Admin check completed"

# Start cron service
service cron start

# Ensure daily cron jobs are executable
chmod +x /etc/cron.daily/*

# Start Apache in foreground
exec apachectl -D FOREGROUND
