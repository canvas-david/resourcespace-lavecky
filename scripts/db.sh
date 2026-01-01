#!/bin/bash
# Render MySQL helper - run queries against production database
# Usage:
#   ./db.sh "SELECT * FROM user LIMIT 5"
#   ./db.sh < query.sql
#   ./db.sh  (interactive mode)

SSH_HOST="srv-d5acinkhg0os73cr9gq0@ssh.oregon.render.com"
MYSQL_CMD='mysql -h mysql-xbeu -u resourcespace -p$DB_PASS resourcespace'

if [ -n "$1" ]; then
    # Query passed as argument
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" "$MYSQL_CMD -e \"$1\""
elif [ ! -t 0 ]; then
    # SQL piped via stdin
    ssh -o StrictHostKeyChecking=no "$SSH_HOST" "$MYSQL_CMD" < /dev/stdin
else
    # Interactive mode
    echo "Connecting to Render MySQL..."
    ssh -o StrictHostKeyChecking=no -t "$SSH_HOST" "$MYSQL_CMD"
fi
