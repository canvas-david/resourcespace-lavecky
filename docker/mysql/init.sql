-- ResourceSpace MySQL initialization script
-- This script runs on first container startup when /var/lib/mysql is empty

-- Application user: SELECT, INSERT, UPDATE, DELETE only
-- Note: MYSQL_USER and MYSQL_PASSWORD env vars create a user with full database privileges
-- This script creates an additional backup user with read-only access

-- Backup user: Read-only + LOCK TABLES for consistent dumps
-- Password is injected via BACKUP_DB_PASS environment variable at runtime
-- This user must be created manually after initial deployment:
--
--   CREATE USER IF NOT EXISTS 'backup'@'%' IDENTIFIED BY '<BACKUP_DB_PASS>';
--   GRANT SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER ON resourcespace.* TO 'backup'@'%';
--   FLUSH PRIVILEGES;

-- Ensure database uses correct character set
ALTER DATABASE resourcespace CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
