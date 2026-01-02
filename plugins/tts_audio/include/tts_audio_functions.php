<?php
/**
 * TTS Audio Functions
 * 
 * Helper functions for the TTS audio plugin
 */

// Field IDs - must match create_tts_fields.sql
// Note: IDs 101-102 are reserved for OCR translation fields (see create_ocr_fields.sql)
define('TTS_FIELD_STATUS', 103);
define('TTS_FIELD_ENGINE', 104);
define('TTS_FIELD_VOICE', 105);
define('TTS_FIELD_GENERATED_AT', 106);

// Source field - Reader Formatted transcription
define('TTS_SOURCE_FIELD', 96);

// Eleven v3 character limit (leave buffer for direction tags)
define('TTS_V3_CHAR_LIMIT', 4800);

/**
 * Get TTS status for a resource
 * 
 * @param int $ref Resource reference
 * @return string|null Status value or null if not set
 */
function tts_audio_get_status($ref)
{
    $value = get_data_by_field($ref, TTS_FIELD_STATUS);
    return !empty($value) ? $value : null;
}

/**
 * Get TTS metadata for a resource
 * 
 * @param int $ref Resource reference
 * @return array Associative array of TTS metadata
 */
function tts_audio_get_metadata($ref)
{
    return [
        'status' => get_data_by_field($ref, TTS_FIELD_STATUS) ?: null,
        'engine' => get_data_by_field($ref, TTS_FIELD_ENGINE) ?: null,
        'voice' => get_data_by_field($ref, TTS_FIELD_VOICE) ?: null,
        'generated_at' => get_data_by_field($ref, TTS_FIELD_GENERATED_AT) ?: null,
    ];
}

/**
 * Check if resource has transcription text available
 * 
 * @param int $ref Resource reference
 * @return bool
 */
function tts_audio_has_transcription($ref)
{
    $value = get_data_by_field($ref, TTS_SOURCE_FIELD);
    return !empty(trim($value));
}

/**
 * Get the TTS audio alternative file for a resource
 * 
 * @param int $ref Resource reference
 * @return array|null Alternative file data or null if not found
 */
function tts_audio_get_alternative($ref)
{
    $alternatives = get_alternative_files($ref);
    
    if (!is_array($alternatives)) {
        return null;
    }
    
    foreach ($alternatives as $alt) {
        $name = strtolower($alt['name'] ?? '');
        $desc = strtolower($alt['description'] ?? '');
        $ext = strtolower($alt['file_extension'] ?? '');
        
        // Look for TTS audio files
        if (strpos($name, 'tts') !== false || strpos($desc, 'tts') !== false) {
            return $alt;
        }
        
        // Also match audio files with "audio" in name
        if ($ext === 'mp3' && strpos($name, 'audio') !== false) {
            return $alt;
        }
    }
    
    return null;
}

/**
 * Check if resource has TTS audio
 * 
 * @param int $ref Resource reference
 * @return bool
 */
function tts_audio_has_audio($ref)
{
    return tts_audio_get_alternative($ref) !== null;
}

/**
 * Get the URL to the TTS audio file
 * 
 * @param int $ref Resource reference
 * @return string|null URL or null if not available
 */
function tts_audio_get_url($ref)
{
    global $baseurl;
    
    $alt = tts_audio_get_alternative($ref);
    if ($alt === null) {
        return null;
    }
    
    // Get the alternative file details
    $alt_ref = $alt['ref'];
    $ext = $alt['file_extension'] ?? 'mp3';
    
    // Use the same URL format as ResourceSpace's view_alternative_files.php
    // noattach=true makes it stream inline instead of download
    return $baseurl . '/pages/download.php?ref=' . (int)$ref . '&ext=' . urlencode($ext) . '&alternative=' . (int)$alt_ref . '&noattach=true&k=';
}

/**
 * Update TTS status field
 * 
 * @param int $ref Resource reference
 * @param string $status Status value (pending, done, failed)
 * @return bool
 */
function tts_audio_update_status($ref, $status)
{
    return update_field($ref, TTS_FIELD_STATUS, $status);
}

/**
 * Get available voices (subset for UI)
 * 
 * @return array Voice options for dropdown
 */
function tts_audio_get_voice_options()
{
    return [
        'omi' => '★ Omi (German)',
        'rachel' => 'Rachel (Neutral, Clear)',
        'adam' => 'Adam (Deep, Authoritative)',
        'antoni' => 'Antoni (Warm, Friendly)',
        'charlotte' => 'Charlotte (British, Sophisticated)',
        'daniel' => 'Daniel (British, Deep)',
        'emily' => 'Emily (American, Calm)',
        'josh' => 'Josh (Young, Dynamic)',
        'matilda' => 'Matilda (Warm, Storytelling)',
        'sam' => 'Sam (Raspy, Authentic)',
        'sarah' => 'Sarah (Soft, News)',
    ];
}

/**
 * Get direction/tone presets for Eleven v3
 * These tags are prepended to text to influence emotional delivery
 * 
 * @return array Direction presets (tag => label)
 */
function tts_audio_get_direction_presets()
{
    return [
        '' => '(No direction)',
        '[gentle, warm]' => 'Gentle & Warm',
        '[elderly, nostalgic]' => 'Elderly & Nostalgic',
        '[sad, reflective]' => 'Sad & Reflective',
        '[storytelling]' => 'Storytelling',
        '[serious, somber]' => 'Serious & Somber',
        '[excited, joyful]' => 'Excited & Joyful',
        '[whispering]' => 'Whispering',
        '[calm, measured]' => 'Calm & Measured',
    ];
}

/**
 * Chunk text into segments under the v3 character limit
 * Splits at paragraph breaks, then sentences, preserving natural boundaries
 * 
 * @param string $text Full text to chunk
 * @param int $max_chars Maximum characters per chunk (default TTS_V3_CHAR_LIMIT)
 * @return array Array of text chunks
 */
function tts_audio_chunk_text($text, $max_chars = TTS_V3_CHAR_LIMIT)
{
    $text = trim($text);
    
    // If under limit, return as single chunk
    if (mb_strlen($text) <= $max_chars) {
        return [$text];
    }
    
    $chunks = [];
    
    // First try splitting by paragraphs (double newline)
    $paragraphs = preg_split('/\n\s*\n/', $text);
    
    $current_chunk = '';
    foreach ($paragraphs as $para) {
        $para = trim($para);
        if (empty($para)) continue;
        
        // If adding this paragraph exceeds limit
        if (mb_strlen($current_chunk) + mb_strlen($para) + 2 > $max_chars) {
            // Save current chunk if not empty
            if (!empty(trim($current_chunk))) {
                $chunks[] = trim($current_chunk);
            }
            
            // If paragraph itself is too long, split by sentences
            if (mb_strlen($para) > $max_chars) {
                $sentence_chunks = tts_audio_chunk_by_sentences($para, $max_chars);
                foreach ($sentence_chunks as $i => $sc) {
                    if ($i === count($sentence_chunks) - 1) {
                        // Last sentence chunk becomes start of new chunk
                        $current_chunk = $sc;
                    } else {
                        $chunks[] = $sc;
                    }
                }
            } else {
                $current_chunk = $para;
            }
        } else {
            // Add paragraph to current chunk
            $current_chunk .= (empty($current_chunk) ? '' : "\n\n") . $para;
        }
    }
    
    // Don't forget the last chunk
    if (!empty(trim($current_chunk))) {
        $chunks[] = trim($current_chunk);
    }
    
    return $chunks;
}

/**
 * Split text by sentences when paragraphs are too long
 * 
 * @param string $text Text to split
 * @param int $max_chars Maximum characters per chunk
 * @return array Array of sentence-bounded chunks
 */
function tts_audio_chunk_by_sentences($text, $max_chars)
{
    // Split by sentence endings (., !, ?) followed by space or newline
    $sentences = preg_split('/(?<=[.!?])\s+/', $text);
    
    $chunks = [];
    $current_chunk = '';
    
    foreach ($sentences as $sentence) {
        $sentence = trim($sentence);
        if (empty($sentence)) continue;
        
        if (mb_strlen($current_chunk) + mb_strlen($sentence) + 1 > $max_chars) {
            if (!empty(trim($current_chunk))) {
                $chunks[] = trim($current_chunk);
            }
            
            // If single sentence is too long, hard split
            if (mb_strlen($sentence) > $max_chars) {
                // Split at word boundaries near the limit
                while (mb_strlen($sentence) > $max_chars) {
                    $split_pos = mb_strrpos(mb_substr($sentence, 0, $max_chars), ' ');
                    if ($split_pos === false) $split_pos = $max_chars;
                    $chunks[] = trim(mb_substr($sentence, 0, $split_pos));
                    $sentence = trim(mb_substr($sentence, $split_pos));
                }
            }
            $current_chunk = $sentence;
        } else {
            $current_chunk .= (empty($current_chunk) ? '' : ' ') . $sentence;
        }
    }
    
    if (!empty(trim($current_chunk))) {
        $chunks[] = trim($current_chunk);
    }
    
    return $chunks;
}

/**
 * Get all TTS audio alternative files for a resource (for multi-part audio)
 * 
 * @param int $ref Resource reference
 * @return array Array of alternative file data, sorted by name
 */
function tts_audio_get_all_alternatives($ref)
{
    $alternatives = get_alternative_files($ref);
    
    if (!is_array($alternatives)) {
        return [];
    }
    
    $tts_files = [];
    foreach ($alternatives as $alt) {
        $name = strtolower($alt['name'] ?? '');
        $desc = strtolower($alt['description'] ?? '');
        $ext = strtolower($alt['file_extension'] ?? '');
        
        // Look for TTS audio files
        if (strpos($name, 'tts') !== false || strpos($desc, 'tts') !== false) {
            $tts_files[] = $alt;
        } elseif ($ext === 'mp3' && strpos($name, 'audio') !== false) {
            $tts_files[] = $alt;
        }
    }
    
    // Sort by name to get parts in order (Part 1, Part 2, etc.)
    usort($tts_files, function($a, $b) {
        return strcmp($a['name'] ?? '', $b['name'] ?? '');
    });
    
    return $tts_files;
}

/**
 * Get URLs for all TTS audio files (for multi-part playback)
 * 
 * @param int $ref Resource reference
 * @return array Array of [name => url] pairs
 */
function tts_audio_get_all_urls($ref)
{
    global $baseurl;
    
    $alternatives = tts_audio_get_all_alternatives($ref);
    if (empty($alternatives)) {
        return [];
    }
    
    $urls = [];
    foreach ($alternatives as $alt) {
        $alt_ref = $alt['ref'];
        $ext = $alt['file_extension'] ?? 'mp3';
        $name = $alt['name'] ?? 'TTS Audio';
        
        $urls[] = [
            'name' => $name,
            'url' => $baseurl . '/pages/download.php?ref=' . (int)$ref . '&ext=' . urlencode($ext) . '&alternative=' . (int)$alt_ref . '&noattach=true&k='
        ];
    }
    
    return $urls;
}

/**
 * Delete all TTS audio files for a resource
 * 
 * @param int $ref Resource reference
 * @return int Number of files deleted
 */
function tts_audio_delete_all($ref)
{
    $alternatives = tts_audio_get_all_alternatives($ref);
    $count = 0;
    
    foreach ($alternatives as $alt) {
        delete_alternative_file($ref, $alt['ref']);
        $count++;
    }
    
    return $count;
}
