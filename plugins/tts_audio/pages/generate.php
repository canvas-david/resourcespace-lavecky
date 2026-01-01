<?php
/**
 * TTS Audio Generation Endpoint
 * 
 * AJAX endpoint to trigger TTS generation for a resource
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

// Check if audio already exists (unless force)
if (!$force && tts_audio_has_audio($ref)) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => true, 'message' => 'Audio already exists', 'skipped' => true]);
        exit;
    }
    exit('Audio already exists');
}

// Get configuration
$python_path = 'python3';
$script_path = '';
get_config_option([], 'tts_audio_python_path', $python_path, 'python3');
get_config_option([], 'tts_audio_script_path', $script_path, '');

// Default script path if not configured
if (empty($script_path)) {
    // Try to find the script relative to ResourceSpace installation
    $possible_paths = [
        dirname(__FILE__, 5) . '/scripts/generate_tts.py',  // Workspace root
        '/var/www/html/scripts/generate_tts.py',             // Docker default
        __DIR__ . '/../../../../scripts/generate_tts.py',    // Relative
    ];
    
    foreach ($possible_paths as $path) {
        if (file_exists($path)) {
            $script_path = $path;
            break;
        }
    }
}

if (empty($script_path) || !file_exists($script_path)) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'TTS script not found. Please configure the script path in plugin settings.']);
        exit;
    }
    exit('TTS script not found');
}

// Update status to pending
tts_audio_update_status($ref, 'pending');

// Build command
$cmd_parts = [
    escapeshellcmd($python_path),
    escapeshellarg($script_path),
    '--resource-id', escapeshellarg($ref),
    '--voice', escapeshellarg($voice),
];

if ($force) {
    $cmd_parts[] = '--force';
}

$cmd_parts[] = '--json';

$cmd = implode(' ', $cmd_parts);

// Set up environment variables
$env = [
    'RS_BASE_URL' => $baseurl,
    'RS_USER' => 'admin',  // Use API user
];

// Get environment variables that should already be set on the server
$required_env = ['RS_API_KEY', 'ELEVENLABS_API_KEY'];
foreach ($required_env as $var) {
    $value = getenv($var);
    if ($value !== false) {
        $env[$var] = $value;
    }
}

// Check required environment variables
if (empty($env['RS_API_KEY']) || empty($env['ELEVENLABS_API_KEY'])) {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'Missing required environment variables (RS_API_KEY, ELEVENLABS_API_KEY)']);
        exit;
    }
    exit('Missing required environment variables');
}

// Execute the script
$descriptorspec = [
    0 => ['pipe', 'r'],  // stdin
    1 => ['pipe', 'w'],  // stdout
    2 => ['pipe', 'w'],  // stderr
];

// Build environment string for the process
$env_string = '';
foreach ($env as $key => $value) {
    $env_string .= "$key=" . escapeshellarg($value) . ' ';
}

$full_cmd = $env_string . $cmd . ' 2>&1';

// Log the command (without sensitive data)
debug('[TTS Audio] Executing TTS generation for resource ' . $ref);

// Execute
$output = [];
$return_var = 0;

// Use proc_open for better control
$process = proc_open($cmd, $descriptorspec, $pipes, null, $env);

if (is_resource($process)) {
    // Close stdin
    fclose($pipes[0]);
    
    // Read stdout
    $stdout = stream_get_contents($pipes[1]);
    fclose($pipes[1]);
    
    // Read stderr
    $stderr = stream_get_contents($pipes[2]);
    fclose($pipes[2]);
    
    // Get exit code
    $return_var = proc_close($process);
    
    // Parse JSON output
    $result = null;
    if (!empty($stdout)) {
        // Find the JSON part (may have log output before it)
        if (preg_match('/\{[^{}]*"success"[^{}]*\}/s', $stdout, $matches)) {
            $result = json_decode($matches[0], true);
        } else {
            $result = json_decode($stdout, true);
        }
    }
    
    if ($ajax) {
        header('Content-Type: application/json');
        
        if ($return_var === 0 && $result && isset($result['success']) && $result['success']) {
            echo json_encode([
                'success' => true,
                'message' => $result['message'] ?? 'Audio generated successfully!',
                'voice' => $voice,
            ]);
        } else {
            $error_message = 'TTS generation failed';
            if ($result && isset($result['message'])) {
                $error_message = $result['message'];
            } elseif (!empty($stderr)) {
                $error_message = trim($stderr);
            } elseif (!empty($stdout)) {
                $error_message = trim($stdout);
            }
            
            echo json_encode([
                'success' => false,
                'message' => $error_message,
            ]);
        }
        exit;
    }
    
    // Non-AJAX response
    if ($return_var === 0 && $result && isset($result['success']) && $result['success']) {
        header('Location: ' . $baseurl . '/pages/view.php?ref=' . $ref);
        exit;
    } else {
        exit('TTS generation failed: ' . ($result['message'] ?? 'Unknown error'));
    }
} else {
    if ($ajax) {
        header('Content-Type: application/json');
        echo json_encode(['success' => false, 'message' => 'Failed to execute TTS script']);
        exit;
    }
    exit('Failed to execute TTS script');
}
