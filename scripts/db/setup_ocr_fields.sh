#!/bin/bash
# Setup OCR/Transcription metadata fields in ResourceSpace
# Run this on the Render resourcespace shell

# MySQL connection (uses internal Render hostname)
MYSQL_HOST="${DB_HOST:-mysql-xbeu}"
MYSQL_USER="${DB_USER:-resourcespace}"
MYSQL_PASS="${DB_PASS}"
MYSQL_DB="${DB_NAME:-resourcespace}"

if [ -z "$MYSQL_PASS" ]; then
    echo "Error: DB_PASS environment variable not set"
    exit 1
fi

echo "Creating OCR/Transcription metadata fields..."

mysql -h "$MYSQL_HOST" -u "$MYSQL_USER" -p"$MYSQL_PASS" "$MYSQL_DB" << 'EOSQL'

-- Delete any existing fields with these IDs
DELETE FROM resource_type_field WHERE ref IN (88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100);

-- OCR Text (Original) - Field 88
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (88, 'ocrtext', 'OCR Text (Original)', 5, 800, 1, 0, 1, 1, 'Transcription', 1, 'Raw OCR output - IMMUTABLE once set', 1);

-- Transcription (Cleaned – Literal) - Field 89
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (89, 'transcriptioncleaned', 'Transcription (Cleaned – Literal)', 5, 810, 1, 0, 1, 1, 'Transcription', 1, 'AI spelling-normalised transcription', 1);

-- OCR Engine - Field 90
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (90, 'ocrengine', 'OCR Engine', 0, 820, 1, 0, 1, 1, 'Transcription', 1, 'e.g., google_document_ai', 1);

-- OCR Language Detected - Field 91
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (91, 'ocrlanguagedetected', 'OCR Language Detected', 0, 830, 1, 0, 1, 1, 'Transcription', 1, 'e.g., en, de, he', 1);

-- OCR Status - Field 92
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (92, 'ocrstatus', 'OCR Status', 0, 840, 1, 0, 1, 1, 'Transcription', 1, 'pending, done, failed', 1);

-- Transcription Method - Field 93
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (93, 'transcriptionmethod', 'Transcription Method', 0, 850, 1, 0, 1, 1, 'Transcription', 1, 'Method used', 1);

-- Transcription Review Status - Field 94
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (94, 'transcriptionreviewstatus', 'Transcription Review Status', 0, 860, 1, 0, 1, 1, 'Transcription', 1, 'unreviewed, reviewed, approved', 1);

-- Transcription Notes - Field 95
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (95, 'transcriptionnotes', 'Transcription Notes', 5, 870, 0, 0, 1, 0, 'Transcription', 0, 'Notes', 1);

-- Transcription (Reader Formatted) - Field 96
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (96, 'transcriptionreaderformatted', 'Transcription (Reader Formatted)', 5, 880, 1, 0, 1, 1, 'Transcription', 1, 'Formatted for reading', 1);

-- Formatting Method - Field 97
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (97, 'formattingmethod', 'Formatting Method', 0, 890, 1, 0, 1, 1, 'Transcription', 1, 'Method used', 1);

-- Formatting Review Status - Field 98
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (98, 'formattingreviewstatus', 'Formatting Review Status', 0, 900, 1, 0, 1, 1, 'Transcription', 1, 'unreviewed, reviewed, approved', 1);

-- Formatting Notes - Field 99
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (99, 'formattingnotes', 'Formatting Notes', 5, 910, 0, 0, 1, 0, 'Transcription', 0, 'Notes', 1);

-- Processing Version - Field 100
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, tab_name, advanced_search, help_text, active)
VALUES (100, 'processingversion', 'Processing Version', 0, 920, 0, 0, 1, 1, 'Transcription', 1, 'e.g., v1.0.0', 1);

-- Show results
SELECT ref, name, title FROM resource_type_field WHERE ref >= 88 AND ref <= 100 ORDER BY ref;

EOSQL

echo ""
echo "Done! Created 13 fields (88-100) in 'Transcription' tab."
echo "Refresh ResourceSpace admin to see them."
