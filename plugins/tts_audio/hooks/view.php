<?php
/**
 * TTS Audio - View Page Hooks
 * 
 * Hooks into the resource view page to display audio player
 */

include_once dirname(__FILE__, 2) . '/include/tts_audio_functions.php';

/**
 * Hook for custom panels on resource view page
 */
function HookTts_audioViewCustompanels()
{
    global $ref, $lang, $baseurl, $baseurl_short, $usersession, $CSRF_token_identifier;
    
    // Get TTS audio if exists
    $audio_url = tts_audio_get_url($ref);
    $has_audio = $audio_url !== null;
    
    // Check if resource has transcription text
    $has_transcription = tts_audio_has_transcription($ref);
    
    // Don't show panel if no audio and no transcription
    if (!$has_audio && !$has_transcription) {
        return false;
    }
    
    // Get default voice from config
    $default_voice = 'rachel';
    get_config_option([], 'tts_audio_default_voice', $default_voice, 'rachel');
    $voice_options = tts_audio_get_voice_options();
    
    // Generate CSRF token for AJAX requests
    $csrf_token = generateCSRFToken($usersession, 'tts_audio_generate');
    
    ?>
    <div class="RecordBox">
        <div class="RecordPanel">
            <div class="Title">
                <i class="fa fa-volume-up"></i>&nbsp;
                <?php echo isset($lang['tts_audio_title']) ? escape($lang['tts_audio_title']) : 'Audio Transcription'; ?>
            </div>
            
            <?php if ($has_audio): ?>
            <!-- Audio Player -->
            <div style="margin: 10px 0;">
                <audio controls preload="metadata" style="width: 100%; max-width: 400px;">
                    <source src="<?php echo escape($audio_url); ?>" type="audio/mpeg">
                    Your browser does not support the audio element.
                </audio>
            </div>
            
            <!-- Regenerate controls -->
            <div style="margin-top: 10px;">
                <select id="tts-voice-select" style="padding: 4px; margin-right: 8px;">
                    <?php foreach ($voice_options as $id => $name): ?>
                    <option value="<?php echo escape($id); ?>" <?php echo $default_voice === $id ? 'selected' : ''; ?>>
                        <?php echo escape($name); ?>
                    </option>
                    <?php endforeach; ?>
                </select>
                <button type="button" class="btn btn-sm" id="tts-regenerate-btn" onclick="ttsGenerate(<?php echo (int)$ref; ?>, true)">
                    <i class="fa fa-refresh"></i>&nbsp;Regenerate
                </button>
                <span id="tts-status" style="margin-left: 10px;"></span>
            </div>
            
            <?php else: ?>
            <!-- Generate controls (no audio yet) -->
            <p style="margin: 10px 0; color: #666;">
                <?php echo isset($lang['tts_no_audio']) ? escape($lang['tts_no_audio']) : 'No audio has been generated yet.'; ?>
            </p>
            <div>
                <select id="tts-voice-select" style="padding: 4px; margin-right: 8px;">
                    <?php foreach ($voice_options as $id => $name): ?>
                    <option value="<?php echo escape($id); ?>" <?php echo $default_voice === $id ? 'selected' : ''; ?>>
                        <?php echo escape($name); ?>
                    </option>
                    <?php endforeach; ?>
                </select>
                <button type="button" class="btn btn-sm" id="tts-generate-btn" onclick="ttsGenerate(<?php echo (int)$ref; ?>, false)">
                    <i class="fa fa-volume-up"></i>&nbsp;Generate Audio
                </button>
                <span id="tts-status" style="margin-left: 10px;"></span>
            </div>
            <?php endif; ?>
        </div>
    </div>
    
    <script>
    function ttsGenerate(resourceId, force) {
        var voice = document.getElementById('tts-voice-select').value;
        var status = document.getElementById('tts-status');
        var btn = document.getElementById(force ? 'tts-regenerate-btn' : 'tts-generate-btn');
        
        btn.disabled = true;
        status.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Generating...';
        
        var xhr = new XMLHttpRequest();
        var url = '<?php echo $baseurl_short; ?>plugins/tts_audio/pages/generate.php';
        var params = 'ref=' + resourceId + '&voice=' + encodeURIComponent(voice) + '&force=' + (force ? '1' : '0') + '&ajax=true&<?php echo $CSRF_token_identifier; ?>=<?php echo $csrf_token; ?>';
        
        xhr.open('POST', url, true);
        xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
        
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                if (xhr.status === 200) {
                    try {
                        var response = JSON.parse(xhr.responseText);
                        if (response.success) {
                            status.innerHTML = '<span style="color:green;"><i class="fa fa-check"></i> ' + (response.message || 'Done!') + '</span>';
                            setTimeout(function() { window.location.reload(); }, 1500);
                        } else {
                            status.innerHTML = '<span style="color:red;"><i class="fa fa-times"></i> ' + (response.message || 'Failed') + '</span>';
                            btn.disabled = false;
                        }
                    } catch (e) {
                        status.innerHTML = '<span style="color:red;">Error parsing response</span>';
                        btn.disabled = false;
                    }
                } else {
                    status.innerHTML = '<span style="color:red;">Server error</span>';
                    btn.disabled = false;
                }
            }
        };
        
        xhr.send(params);
    }
    </script>
    <?php
    
    return false; // Allow further custom panels
}
