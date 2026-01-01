<?php
/**
 * TTS Audio Functions
 * 
 * Helper functions for the TTS audio plugin
 */

// Field IDs - must match create_tts_fields.sql
define('TTS_FIELD_STATUS', 101);
define('TTS_FIELD_ENGINE', 102);
define('TTS_FIELD_VOICE', 103);
define('TTS_FIELD_GENERATED_AT', 104);

// Source field - Reader Formatted transcription
define('TTS_SOURCE_FIELD', 96);

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
    
    // Get the alternative file path
    $alt_ref = $alt['ref'];
    $ext = $alt['file_extension'];
    
    // Build the URL to access the alternative file
    // ResourceSpace typically serves alternative files via pages/download.php
    return $baseurl . '/pages/download.php?ref=' . $ref . '&alternative=' . $alt_ref . '&ext=' . $ext . '&k=';
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
