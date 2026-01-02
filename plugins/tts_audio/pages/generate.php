<?php
/**
 * TTS Audio Generation Endpoint (Eleven v3)
 * 
 * AJAX endpoint to trigger TTS generation for a resource.
 * Supports:
 * - Eleven v3 model with emotional dialogue
 * - Direction/tone presets
 * - Auto-chunking for texts > 4800 chars
 * - Multi-part audio generation
 */

include '../../../include/boot.php';
include '../../../include/authenticate.php';

include_once dirname(__FILE__, 2) . '/include/tts_audio_functions.php';

// Check if this is an AJAX request
$ajax = getval('ajax', '') === 'true';

// Get parameters
$ref = getval('ref', '', true);
$voice = getval('voice', 'omi');
$direction = getval('direction', '');  // Emotion/direction tag to prepend
$force = getval('force', '0') === '1';

// Validate resource ID
if (!is_numeric($ref) || $ref <= 0) {
    json_error('Invalid resource ID');
}

$ref = (int)$ref;

// Check permission to edit this resource
if (!get_edit_access($ref)) {
    json_error('Permission denied');
}

// Check if transcription exists
if (!tts_audio_has_transcription($ref)) {
    json_error('No transcription text available');
}

// If force, delete ALL existing TTS audio files
if ($force) {
    $deleted = tts_audio_delete_all($ref);
}

// Check if audio already exists (after potential deletion)
if (tts_audio_has_audio($ref)) {
    json_success('Audio already exists', ['skipped' => true]);
}

// Get transcription text - try TTS Script field first (with emotion tags), fallback to Formatted
$transcription = '';
$source_field = 'formatted';

// Try TTS Script field first (Field 107 - pre-annotated with emotion tags)
if (defined('TTS_SCRIPT_FIELD')) {
    $transcription = get_data_by_field($ref, TTS_SCRIPT_FIELD);
    if (!empty(trim($transcription))) {
        $source_field = 'tts_script';
    }
}

// Fall back to Formatted Transcription (Field 96)
if (empty(trim($transcription))) {
    $transcription = get_data_by_field($ref, TTS_SOURCE_FIELD);
    $source_field = 'formatted';
}

if (empty(trim($transcription))) {
    json_error('No transcription text found');
}

// Get ElevenLabs API key
$elevenlabs_key = getenv('ELEVENLABS_API_KEY');
if (empty($elevenlabs_key)) {
    json_error('ELEVENLABS_API_KEY not configured');
}

// Voice ID mapping
$voice_ids = [
    'omi' => 'RLUByKTYYITeAvbZnWex',      // Custom cloned voice (German)
    'rachel' => '21m00Tcm4TlvDq8ikWAM',
    'adam' => 'pNInz6obpgDQGcFmaJgB',
    'antoni' => 'ErXwobaYiN019PkySvjV',
    'charlotte' => 'XB0fDUnXU5powFXDhCwa',
    'daniel' => 'onwK4e9ZLuTAKqWW03F9',
    'emily' => 'LcfcDJNUP1GQjkzn1xUU',
    'josh' => 'TxGEqnHWrfWFTfGW9XjX',
    'matilda' => 'XrExE9yKIg1WjnnlVkGX',
    'sam' => 'yoZ06aMxZJJ28mfd3POQ',
    'sarah' => 'EXAVITQu4vr4xnSDxMaL',
];

$voice_id = $voice_ids[$voice] ?? $voice_ids['omi'];
$model = 'eleven_v3';  // v3: emotional, expressive, 70+ languages

// Voice settings optimized for cloned voice accuracy:
// - Higher similarity_boost (0.85) = closer to original voice
// - Higher stability (0.65) = more consistent while allowing expression
// - use_speaker_boost: enhances similarity for cloned voices
$is_cloned_voice = ($voice === 'omi');
$voice_settings = [
    'stability' => $is_cloned_voice ? 0.65 : 0.50,
    'similarity_boost' => $is_cloned_voice ? 0.85 : 0.75,
    'use_speaker_boost' => $is_cloned_voice
];

// Chunk the text if needed (v3 has 5000 char limit)
$chunks = tts_audio_chunk_text($transcription);
$total_parts = count($chunks);

// Track generated files
$generated_files = [];
$errors = [];

foreach ($chunks as $part_num => $chunk_text) {
    // Clean text for TTS
    $text_to_generate = tts_audio_clean_text($chunk_text);
    
    // Prepend direction tag if specified
    if (!empty($direction)) {
        $text_to_generate = $direction . ' ' . $text_to_generate;
    }
    
    // Call ElevenLabs API
    $api_url = "https://api.elevenlabs.io/v1/text-to-speech/{$voice_id}";
    
    $post_data = json_encode([
        'text' => $text_to_generate,
        'model_id' => $model,
        'voice_settings' => $voice_settings
    ], JSON_UNESCAPED_UNICODE);
    
    $ch = curl_init($api_url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $post_data,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => [
            'Accept: audio/mpeg',
            'Content-Type: application/json',
            'xi-api-key: ' . $elevenlabs_key
        ],
        CURLOPT_TIMEOUT => 180  // v3 can be slower, allow 3 minutes
    ]);
    
    $audio_data = curl_exec($ch);
    $http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $curl_error = curl_error($ch);
    curl_close($ch);
    
    if ($http_code !== 200 || empty($audio_data)) {
        $error_msg = 'ElevenLabs API error';
        if ($curl_error) {
            $error_msg .= ": $curl_error";
        } elseif ($http_code !== 200) {
            $error_msg .= " (HTTP $http_code)";
            // Try to parse error response
            $error_json = json_decode($audio_data, true);
            if (isset($error_json['detail']['message'])) {
                $error_msg .= ": " . $error_json['detail']['message'];
            } elseif (isset($error_json['detail'])) {
                $error_msg .= ": " . (is_string($error_json['detail']) ? $error_json['detail'] : json_encode($error_json['detail']));
            }
        }
        $errors[] = "Part " . ($part_num + 1) . ": " . $error_msg;
        continue;
    }
    
    // Save audio to temp file
    $temp_base = tempnam(sys_get_temp_dir(), 'tts_');
    $temp_file = $temp_base . '.mp3';
    if (file_exists($temp_base)) {
        unlink($temp_base);
    }
    $bytes_written = file_put_contents($temp_file, $audio_data);
    
    if ($bytes_written === false || $bytes_written === 0) {
        $errors[] = "Part " . ($part_num + 1) . ": Failed to write audio to temp file";
        continue;
    }
    
    // Build file name and description
    $part_label = $total_parts > 1 ? " - Part " . ($part_num + 1) : "";
    $file_name = "TTS Audio" . $part_label;
    $direction_label = !empty($direction) ? ", direction: " . trim($direction, '[]') : "";
    $source_label = $source_field === 'tts_script' ? ", source: TTS Script" : "";
    $description = "Text-to-speech audio (voice: $voice, model: $model{$direction_label}{$source_label})";
    
    // Add alternative file record to database
    $file_size = filesize($temp_file);
    $alt_ref = add_alternative_file($ref, $file_name, $description, 'tts_audio.mp3', 'mp3', $file_size, '');
    
    if (!$alt_ref) {
        unlink($temp_file);
        $errors[] = "Part " . ($part_num + 1) . ": Failed to create alternative file record";
        continue;
    }
    
    // Get the target path for the alternative file
    $target_path = get_resource_path($ref, true, "", true, "mp3", -1, 1, false, "", $alt_ref);
    
    // Ensure the directory exists
    $target_dir = dirname($target_path);
    if (!is_dir($target_dir)) {
        mkdir($target_dir, 0777, true);
    }
    
    // Copy the temp file to the target location
    if (!copy($temp_file, $target_path)) {
        unlink($temp_file);
        delete_alternative_file($ref, $alt_ref);
        $errors[] = "Part " . ($part_num + 1) . ": Failed to copy audio file to filestore";
        continue;
    }
    
    // Set proper permissions
    chmod($target_path, 0664);
    
    // Clean up temp file
    unlink($temp_file);
    
    $generated_files[] = [
        'part' => $part_num + 1,
        'alt_ref' => $alt_ref,
        'name' => $file_name
    ];
}

// Check results
if (empty($generated_files)) {
    json_error('Failed to generate any audio: ' . implode('; ', $errors));
}

if (!empty($errors)) {
    // Partial success
    json_success('Audio generated with some errors', [
        'voice' => $voice,
        'parts' => count($generated_files),
        'total_parts' => $total_parts,
        'errors' => $errors,
        'files' => $generated_files
    ]);
}

// Full success
json_success('Audio generated successfully!', [
    'voice' => $voice,
    'parts' => count($generated_files),
    'source' => $source_field,
    'files' => $generated_files
]);

// --- Helper functions ---

function json_error($message) {
    global $ajax, $baseurl, $ref;
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => $message]);
        exit;
    }
    exit($message);
}

function json_success($message, $data = []) {
    global $ajax, $baseurl, $ref;
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(array_merge(['success' => true, 'message' => $message], $data));
        exit;
    }
    // Non-AJAX: redirect back to resource
    header('Location: ' . $baseurl . '/pages/view.php?ref=' . $ref);
    exit;
}
