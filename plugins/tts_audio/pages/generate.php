<?php
/**
 * TTS Audio Generation Endpoint
 * 
 * AJAX endpoint to trigger TTS generation for a resource.
 * Python generates the audio file, PHP handles the ResourceSpace upload.
 */

include '../../../include/boot.php';
include '../../../include/authenticate.php';

include_once dirname(__FILE__, 2) . '/include/tts_audio_functions.php';

// Check if this is an AJAX request
$ajax = getval('ajax', '') === 'true';

// Get parameters
$ref = getval('ref', '', true);
$voice = getval('voice', 'rachel');
$force = getval('force', '0') === '1';

// Validate resource ID
if (!is_numeric($ref) || $ref <= 0) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'Invalid resource ID']);
        exit;
    }
    exit('Invalid resource ID');
}

$ref = (int)$ref;

// Check permission to edit this resource
if (!get_edit_access($ref)) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'Permission denied']);
        exit;
    }
    exit('Permission denied');
}

// Check if transcription exists
if (!tts_audio_has_transcription($ref)) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'No transcription text available']);
        exit;
    }
    exit('No transcription text available');
}

// If force, delete existing TTS audio
if ($force) {
    $existing = tts_audio_get_alternative($ref);
    if ($existing) {
        delete_alternative_file($ref, $existing['ref']);
    }
}

// Check if audio already exists (after potential deletion)
if (tts_audio_has_audio($ref)) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => true, 'message' => 'Audio already exists', 'skipped' => true]);
        exit;
    }
    exit('Audio already exists');
}

// Get transcription text
$transcription = get_data_by_field($ref, TTS_SOURCE_FIELD);
if (empty(trim($transcription))) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'No transcription text found']);
        exit;
    }
    exit('No transcription text found');
}

// Get ElevenLabs API key
$elevenlabs_key = getenv('ELEVENLABS_API_KEY');
if (empty($elevenlabs_key)) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'ELEVENLABS_API_KEY not configured']);
        exit;
    }
    exit('ELEVENLABS_API_KEY not configured');
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

$voice_id = $voice_ids[$voice] ?? $voice_ids['rachel'];
$model = 'eleven_multilingual_v2';

// Call ElevenLabs API
$api_url = "https://api.elevenlabs.io/v1/text-to-speech/{$voice_id}";

$post_data = json_encode([
    'text' => $transcription,
    'model_id' => $model,
    'voice_settings' => [
        'stability' => 0.5,
        'similarity_boost' => 0.75
    ]
]);

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
    CURLOPT_TIMEOUT => 120
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
        }
    }
    
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => $error_msg]);
        exit;
    }
    exit($error_msg);
}

// Save audio to temp file
$temp_base = tempnam(sys_get_temp_dir(), 'tts_');
$temp_file = $temp_base . '.mp3';
// Remove the original temp file created by tempnam
if (file_exists($temp_base)) {
    unlink($temp_base);
}
$bytes_written = file_put_contents($temp_file, $audio_data);

if ($bytes_written === false || $bytes_written === 0) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'Failed to write audio to temp file']);
        exit;
    }
    exit('Failed to write audio to temp file');
}

// Add alternative file record to database
$description = "Text-to-speech audio (voice: $voice, model: $model)";
$file_size = filesize($temp_file);
$alt_ref = add_alternative_file($ref, 'TTS Audio', $description, 'tts_audio.mp3', 'mp3', $file_size, '');

if (!$alt_ref) {
    unlink($temp_file);
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'Failed to create alternative file record']);
        exit;
    }
    exit('Failed to create alternative file record');
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
    // Clean up on failure
    unlink($temp_file);
    delete_alternative_file($ref, $alt_ref);
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'Failed to copy audio file to filestore']);
        exit;
    }
    exit('Failed to copy audio file to filestore');
}

// Set proper permissions
chmod($target_path, 0664);

// Clean up temp file
unlink($temp_file);

// Success
if ($ajax) {
    header('Content-Type: application/json');
    echo json_encode([
        'success' => true,
        'message' => 'Audio generated successfully!',
        'voice' => $voice,
        'alt_ref' => $alt_ref
    ]);
    exit;
}

// Non-AJAX: redirect back to resource
header('Location: ' . $baseurl . '/pages/view.php?ref=' . $ref);
exit;
