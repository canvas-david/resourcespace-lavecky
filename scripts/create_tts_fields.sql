-- ResourceSpace TTS Audio Fields Setup
-- Run via: mysql -h mysql-xbeu -u resourcespace -p resourcespace < create_tts_fields.sql
--
-- NOTE: Field IDs 101-102 are reserved for OCR translation fields (see create_ocr_fields.sql)
--       TTS fields use IDs 103-106 to avoid conflicts

-- Field types in ResourceSpace:
-- 0 = Text box (single line)
-- 1 = Dropdown (select)
-- 2 = Check box list
-- 4 = Date
-- 5 = Text box (multi-line/textarea)
-- 7 = Category tree
-- 8 = Dynamic keywords list

-- First, delete any existing fields with these IDs (in case of partial setup)
DELETE FROM resource_type_field WHERE ref IN (103, 104, 105, 106);

-- Delete any orphaned data for these fields
DELETE FROM resource_data WHERE resource_type_field IN (103, 104, 105, 106);

-- Create TTS Status - Field 103
-- Values: pending, done, failed
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, display_template, tab_name, smart_theme_name, exiftool_field, advanced_search, simple_search, help_text, display_as_dropdown, tooltip_text, regexp_filter, hide_when_uploading, hide_when_restricted, required, linked_data_field, automatic_nodes_ordering, display_condition, onchange_macro, field_constraint, active, sync_field)
VALUES (103, 'ttsstatus', 'TTS Status', 0, 930, 1, 0, 1, 1, '', 'Transcription', '', '', 1, 0, 'TTS generation status: pending, done, failed', 0, '', '', 0, 0, 0, '', 1, '', '', 0, 1, 0);

-- Create TTS Engine - Field 104
-- Values: elevenlabs
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, display_template, tab_name, smart_theme_name, exiftool_field, advanced_search, simple_search, help_text, display_as_dropdown, tooltip_text, regexp_filter, hide_when_uploading, hide_when_restricted, required, linked_data_field, automatic_nodes_ordering, display_condition, onchange_macro, field_constraint, active, sync_field)
VALUES (104, 'ttsengine', 'TTS Engine', 0, 940, 1, 0, 1, 1, '', 'Transcription', '', '', 1, 0, 'Text-to-speech engine used (e.g., elevenlabs)', 0, '', '', 0, 0, 0, '', 1, '', '', 0, 1, 0);

-- Create TTS Voice - Field 105
-- Values: voice name/ID used for generation
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, display_template, tab_name, smart_theme_name, exiftool_field, advanced_search, simple_search, help_text, display_as_dropdown, tooltip_text, regexp_filter, hide_when_uploading, hide_when_restricted, required, linked_data_field, automatic_nodes_ordering, display_condition, onchange_macro, field_constraint, active, sync_field)
VALUES (105, 'ttsvoice', 'TTS Voice', 0, 950, 1, 0, 1, 1, '', 'Transcription', '', '', 1, 0, 'Voice name or ID used for TTS generation', 0, '', '', 0, 0, 0, '', 1, '', '', 0, 1, 0);

-- Create TTS Generated At - Field 106
-- Values: timestamp of last generation
INSERT INTO resource_type_field (ref, name, title, type, order_by, keywords_index, resource_type, display_field, enable_advanced_search, display_template, tab_name, smart_theme_name, exiftool_field, advanced_search, simple_search, help_text, display_as_dropdown, tooltip_text, regexp_filter, hide_when_uploading, hide_when_restricted, required, linked_data_field, automatic_nodes_ordering, display_condition, onchange_macro, field_constraint, active, sync_field)
VALUES (106, 'ttsgeneratedat', 'TTS Generated At', 0, 960, 0, 0, 1, 1, '', 'Transcription', '', '', 1, 0, 'Timestamp of TTS audio generation', 0, '', '', 0, 0, 0, '', 1, '', '', 0, 1, 0);

-- Verify creation
SELECT ref, name, title, type FROM resource_type_field WHERE ref >= 103 AND ref <= 106 ORDER BY ref;
