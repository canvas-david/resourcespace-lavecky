-- ResourceSpace OCR/Transcription Fields Setup
-- Run via: mysql -h mysql-xbeu -u resourcespace -p resourcespace < create_ocr_fields.sql
--
-- Creates a multi-tab metadata structure:
--   Tab 2: Transcription - Readable content
--   Tab 3: Review - Status and notes for reviewers
--   Tab 4: Technical - Processing metadata
--   Tab 5: Archival - Raw OCR output

-- Field types: 0 = single line, 5 = multi-line textarea

-- =============================================================================
-- TABS SETUP
-- =============================================================================

INSERT IGNORE INTO tab (ref, name, order_by) VALUES (2, 'Transcription', 20);
INSERT IGNORE INTO tab (ref, name, order_by) VALUES (3, 'Review', 30);
INSERT IGNORE INTO tab (ref, name, order_by) VALUES (4, 'Technical', 40);
INSERT IGNORE INTO tab (ref, name, order_by) VALUES (5, 'Archival', 50);

UPDATE tab SET name = 'Transcription' WHERE ref = 2;
UPDATE tab SET name = 'Review' WHERE ref = 3;
UPDATE tab SET name = 'Technical' WHERE ref = 4;
UPDATE tab SET name = 'Archival' WHERE ref = 5;

-- =============================================================================
-- CLEAN SLATE
-- =============================================================================

DELETE FROM resource_type_field WHERE ref IN (88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102);
DELETE FROM resource_data WHERE resource_type_field IN (88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102);

-- =============================================================================
-- TAB 2: TRANSCRIPTION (Readable content for end users)
-- =============================================================================

-- Literal Transcription - Field 89
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (89, 'transcriptioncleaned', 'Literal Transcription', 5, 10, 1, 1, 2, 1, 1, 'AI-cleaned transcription preserving original wording with normalized spelling', 1, 1);

-- Reader-Friendly Version - Field 96
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (96, 'transcriptionreaderformatted', 'Reader-Friendly Version', 5, 20, 1, 1, 2, 1, 0, 'Formatted transcription with modern punctuation and paragraphs', 1, 1);

-- English Translation - Field 101
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (101, 'englishtranslation', 'English Translation', 5, 30, 1, 1, 2, 1, 1, 'Machine-translated English version of the OCR text', 1, 1);

-- Translation Source Language - Field 102
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (102, 'translationsourcelanguage', 'Translation Source Language', 0, 40, 1, 1, 2, 1, 0, 'Original language of the document (e.g., pl, he, de)', 1, 1);

-- =============================================================================
-- TAB 3: REVIEW (Status and notes for reviewers/editors)
-- =============================================================================

-- Transcription Status - Field 94
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (94, 'transcriptionreviewstatus', 'Transcription Status', 0, 10, 1, 1, 3, 1, 0, 'Review status: unreviewed, reviewed, approved', 1, 1);

-- Transcription Notes - Field 95
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (95, 'transcriptionnotes', 'Transcription Notes', 5, 20, 0, 1, 3, 0, 0, 'Notes about the transcription quality or issues', 1, 1);

-- Formatting Status - Field 98
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (98, 'formattingreviewstatus', 'Formatting Status', 0, 30, 1, 1, 3, 1, 0, 'Review status: unreviewed, reviewed, approved', 1, 1);

-- Formatting Notes - Field 99
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (99, 'formattingnotes', 'Formatting Notes', 5, 40, 0, 1, 3, 0, 0, 'Notes about the formatting quality or issues', 1, 1);

-- =============================================================================
-- TAB 4: TECHNICAL (Processing metadata)
-- =============================================================================

-- Status - Field 92
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (92, 'ocrstatus', 'Status', 0, 10, 1, 1, 4, 1, 0, 'OCR processing status: pending, done, failed', 1, 1);

-- Engine - Field 90
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (90, 'ocrengine', 'Engine', 0, 20, 1, 1, 4, 1, 0, 'OCR engine used (e.g., google_document_ai)', 1, 1);

-- Detected Language - Field 91
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (91, 'ocrlanguagedetected', 'Detected Language', 0, 30, 1, 1, 4, 1, 0, 'Detected language code (e.g., en, de, he)', 1, 1);

-- Transcription Method - Field 93
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (93, 'transcriptionmethod', 'Transcription Method', 0, 40, 1, 1, 4, 1, 0, 'AI method used for transcription cleanup', 1, 1);

-- Formatting Method - Field 97
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (97, 'formattingmethod', 'Formatting Method', 0, 50, 1, 1, 4, 1, 0, 'AI method used for reader formatting', 1, 1);

-- Pipeline Version - Field 100
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (100, 'processingversion', 'Pipeline Version', 0, 60, 0, 1, 4, 1, 0, 'Processing pipeline version (e.g., v1.0.0)', 1, 1);

-- =============================================================================
-- TAB 5: ARCHIVAL (Raw OCR - immutable source)
-- =============================================================================

-- Original OCR Output - Field 88 - IMMUTABLE
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, display_field, tab, advanced_search, simple_search, help_text, hide_when_uploading, active)
VALUES (88, 'ocrtext', 'Original OCR Output', 5, 10, 1, 1, 5, 1, 0, 'Raw OCR output - IMMUTABLE archival record, never overwritten', 1, 1);

-- =============================================================================
-- VERIFY
-- =============================================================================

SELECT t.name as tab_name, f.ref, f.title, f.order_by 
FROM resource_type_field f 
JOIN tab t ON f.tab = t.ref 
WHERE f.ref BETWEEN 88 AND 102 
ORDER BY t.order_by, f.order_by;
