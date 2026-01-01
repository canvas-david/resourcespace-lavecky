<?php
/**
 * TTS Audio - View Page Hooks
 * 
 * Hooks into the resource view page to display audio player or generate button
 */

include_once dirname(__FILE__, 2) . '/include/tts_audio_functions.php';

/**
 * Hook that fires in the resource tools section
 * Adds TTS audio player or generate button
 */
function HookTts_audioViewRenderbeforeresourcedetails()
{
    global $ref, $resource, $lang, $baseurl, $baseurl_short;
    
    // Check if resource has transcription text
    $has_transcription = tts_audio_has_transcription($ref);
    
    // Get TTS audio if exists
    $audio_url = tts_audio_get_url($ref);
    $has_audio = $audio_url !== null;
    
    // Get TTS metadata
    $metadata = tts_audio_get_metadata($ref);
    
    // Get default voice from config
    $default_voice = get_config_option(null, 'tts_audio_default_voice', 'rachel');
    $voice_options = tts_audio_get_voice_options();
    
    ?>
    <div class="tts-audio-container" id="tts-audio-section">
        <h4>
            <i class="fa fa-volume-up"></i>
            <?php echo isset($lang['tts_audio_title']) ? escape($lang['tts_audio_title']) : 'Audio Transcription'; ?>
        </h4>
        
        <?php if ($has_audio): ?>
        <!-- Audio Player -->
        <div class="tts-audio-player" id="tts-player">
            <audio controls preload="metadata">
                <source src="<?php echo escape($audio_url); ?>" type="audio/mpeg">
                <?php echo isset($lang['tts_audio_not_supported']) ? escape($lang['tts_audio_not_supported']) : 'Your browser does not support the audio element.'; ?>
            </audio>
        </div>
        
        <?php if ($metadata['voice'] || $metadata['generated_at']): ?>
        <div class="tts-audio-meta">
            <?php if ($metadata['voice']): ?>
            <span>
                <span class="label"><?php echo isset($lang['tts_voice']) ? escape($lang['tts_voice']) : 'Voice:'; ?></span>
                <?php echo escape($metadata['voice']); ?>
            </span>
            <?php endif; ?>
            <?php if ($metadata['generated_at']): ?>
            <span>
                <span class="label"><?php echo isset($lang['tts_generated']) ? escape($lang['tts_generated']) : 'Generated:'; ?></span>
                <?php echo escape($metadata['generated_at']); ?>
            </span>
            <?php endif; ?>
        </div>
        <?php endif; ?>
        
        <!-- Regenerate controls -->
        <div class="tts-generate-section" style="margin-top: 12px;">
            <div class="tts-generate-controls">
                <select id="tts-voice-select" class="tts-voice-select">
                    <?php foreach ($voice_options as $id => $name): ?>
                    <option value="<?php echo escape($id); ?>" <?php echo ($metadata['voice'] === $id || (!$metadata['voice'] && $default_voice === $id)) ? 'selected' : ''; ?>>
                        <?php echo escape($name); ?>
                    </option>
                    <?php endforeach; ?>
                </select>
                <button type="button" class="tts-regenerate-btn" id="tts-regenerate-btn" onclick="ttsRegenerate(<?php echo (int)$ref; ?>)">
                    <i class="fa fa-refresh"></i>
                    <?php echo isset($lang['tts_regenerate']) ? escape($lang['tts_regenerate']) : 'Regenerate'; ?>
                </button>
            </div>
            <div class="tts-loading" id="tts-loading">
                <div class="spinner"></div>
                <span><?php echo isset($lang['tts_generating']) ? escape($lang['tts_generating']) : 'Generating audio...'; ?></span>
            </div>
            <div class="tts-status" id="tts-status" style="display: none;"></div>
        </div>
        
        <?php elseif ($has_transcription): ?>
        <!-- Generate controls (no audio yet) -->
        <div class="tts-generate-section">
            <p style="margin: 0 0 12px 0; color: #6c757d; font-size: 13px;">
                <?php echo isset($lang['tts_no_audio']) ? escape($lang['tts_no_audio']) : 'No audio has been generated yet.'; ?>
            </p>
            <div class="tts-generate-controls">
                <select id="tts-voice-select" class="tts-voice-select">
                    <?php foreach ($voice_options as $id => $name): ?>
                    <option value="<?php echo escape($id); ?>" <?php echo $default_voice === $id ? 'selected' : ''; ?>>
                        <?php echo escape($name); ?>
                    </option>
                    <?php endforeach; ?>
                </select>
                <button type="button" class="tts-generate-btn" id="tts-generate-btn" onclick="ttsGenerate(<?php echo (int)$ref; ?>)">
                    <i class="fa fa-volume-up"></i>
                    <?php echo isset($lang['tts_generate']) ? escape($lang['tts_generate']) : 'Generate Audio'; ?>
                </button>
            </div>
            <div class="tts-loading" id="tts-loading">
                <div class="spinner"></div>
                <span><?php echo isset($lang['tts_generating']) ? escape($lang['tts_generating']) : 'Generating audio... This may take a minute.'; ?></span>
            </div>
            <div class="tts-status" id="tts-status" style="display: none;"></div>
        </div>
        
        <?php else: ?>
        <!-- No transcription available -->
        <p class="tts-no-transcription">
            <?php echo isset($lang['tts_no_transcription']) ? escape($lang['tts_no_transcription']) : 'No transcription text available. Generate a transcription first to enable audio.'; ?>
        </p>
        <?php endif; ?>
    </div>
    
    <script>
    var ttsBaseUrl = '<?php echo $baseurl_short; ?>';
    
    function ttsGenerate(resourceId) {
        ttsDoGenerate(resourceId, false);
    }
    
    function ttsRegenerate(resourceId) {
        ttsDoGenerate(resourceId, true);
    }
    
    function ttsDoGenerate(resourceId, force) {
        var voice = document.getElementById('tts-voice-select').value;
        var generateBtn = document.getElementById('tts-generate-btn');
        var regenerateBtn = document.getElementById('tts-regenerate-btn');
        var loading = document.getElementById('tts-loading');
        var status = document.getElementById('tts-status');
        
        // Disable buttons and show loading
        if (generateBtn) generateBtn.disabled = true;
        if (regenerateBtn) regenerateBtn.disabled = true;
        loading.classList.add('active');
        status.style.display = 'none';
        
        // Make AJAX request
        var xhr = new XMLHttpRequest();
        var url = ttsBaseUrl + 'plugins/tts_audio/pages/generate.php';
        var params = 'ref=' + resourceId + '&voice=' + encodeURIComponent(voice) + '&force=' + (force ? '1' : '0') + '&ajax=true';
        
        xhr.open('POST', url, true);
        xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
        
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                loading.classList.remove('active');
                
                if (xhr.status === 200) {
                    try {
                        var response = JSON.parse(xhr.responseText);
                        if (response.success) {
                            status.className = 'tts-status success';
                            status.textContent = response.message || 'Audio generated successfully!';
                            status.style.display = 'block';
                            
                            // Reload page to show the new audio player
                            setTimeout(function() {
                                window.location.reload();
                            }, 1500);
                        } else {
                            status.className = 'tts-status error';
                            status.textContent = response.message || 'Failed to generate audio.';
                            status.style.display = 'block';
                            if (generateBtn) generateBtn.disabled = false;
                            if (regenerateBtn) regenerateBtn.disabled = false;
                        }
                    } catch (e) {
                        status.className = 'tts-status error';
                        status.textContent = 'Invalid response from server.';
                        status.style.display = 'block';
                        if (generateBtn) generateBtn.disabled = false;
                        if (regenerateBtn) regenerateBtn.disabled = false;
                    }
                } else {
                    status.className = 'tts-status error';
                    status.textContent = 'Server error: ' + xhr.status;
                    status.style.display = 'block';
                    if (generateBtn) generateBtn.disabled = false;
                    if (regenerateBtn) regenerateBtn.disabled = false;
                }
            }
        };
        
        xhr.send(params);
    }
    </script>
    <?php
    
    return false;
}
