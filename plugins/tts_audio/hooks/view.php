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
    
    // Get all TTS audio files (supports multi-part)
    $audio_urls = tts_audio_get_all_urls($ref);
    $has_audio = !empty($audio_urls);
    
    // Check if resource has transcription text
    $has_transcription = tts_audio_has_transcription($ref);
    
    // Don't show panel if no audio and no transcription
    if (!$has_audio && !$has_transcription) {
        return false;
    }
    
    // Get default voice from config
    $default_voice = 'omi';  // Default to Omi for this project
    get_config_option([], 'tts_audio_default_voice', $default_voice, 'omi');
    $voice_options = tts_audio_get_voice_options();
    $direction_presets = tts_audio_get_direction_presets();
    
    // Generate CSRF token for AJAX requests
    $csrf_token = generateCSRFToken($usersession, 'tts_audio_generate');
    
    ?>
    <div class="RecordBox">
        <div class="RecordPanel">
            <div class="Title">
                <i class="fa fa-volume-up"></i>&nbsp;
                <?php echo isset($lang['tts_audio_title']) ? escape($lang['tts_audio_title']) : 'Audio Transcription'; ?>
                <span style="font-size: 0.8em; color: #888; margin-left: 8px;">(Eleven v3)</span>
            </div>
            
            <?php if ($has_audio): ?>
            <!-- Audio Player(s) -->
            <div style="margin: 10px 0;">
                <?php if (count($audio_urls) === 1): ?>
                <!-- Single audio file -->
                <audio controls preload="metadata" style="width: 100%; max-width: 500px;">
                    <source src="<?php echo escape($audio_urls[0]['url']); ?>" type="audio/mpeg">
                    Your browser does not support the audio element.
                </audio>
                <?php else: ?>
                <!-- Multi-part playlist -->
                <div id="tts-playlist" style="margin-bottom: 10px;">
                    <?php foreach ($audio_urls as $i => $audio): ?>
                    <div class="tts-track" data-index="<?php echo $i; ?>" style="padding: 4px 8px; margin: 2px 0; background: <?php echo $i === 0 ? '#e8f4e8' : '#f5f5f5'; ?>; border-radius: 4px; cursor: pointer;">
                        <i class="fa fa-play-circle"></i>&nbsp;
                        <?php echo escape($audio['name']); ?>
                    </div>
                    <?php endforeach; ?>
                </div>
                <audio id="tts-player" controls preload="metadata" style="width: 100%; max-width: 500px;">
                    <source src="<?php echo escape($audio_urls[0]['url']); ?>" type="audio/mpeg">
                    Your browser does not support the audio element.
                </audio>
                <script>
                (function() {
                    var urls = <?php echo json_encode(array_column($audio_urls, 'url')); ?>;
                    var tracks = document.querySelectorAll('.tts-track');
                    var player = document.getElementById('tts-player');
                    var currentIndex = 0;
                    
                    function playTrack(index) {
                        if (index >= urls.length) return;
                        currentIndex = index;
                        player.src = urls[index];
                        player.play();
                        tracks.forEach(function(t, i) {
                            t.style.background = i === index ? '#e8f4e8' : '#f5f5f5';
                        });
                    }
                    
                    tracks.forEach(function(track, i) {
                        track.addEventListener('click', function() { playTrack(i); });
                    });
                    
                    // Auto-play next track when current ends
                    player.addEventListener('ended', function() {
                        if (currentIndex < urls.length - 1) {
                            playTrack(currentIndex + 1);
                        }
                    });
                })();
                </script>
                <?php endif; ?>
            </div>
            
            <!-- Regenerate controls -->
            <div style="margin-top: 10px;">
                <div style="margin-bottom: 8px;">
                    <label style="font-size: 0.9em; color: #666;">Direction:</label>
                    <select id="tts-direction-select" style="padding: 4px; margin-left: 4px;">
                        <?php foreach ($direction_presets as $tag => $label): ?>
                        <option value="<?php echo escape($tag); ?>"><?php echo escape($label); ?></option>
                        <?php endforeach; ?>
                    </select>
                </div>
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
            <p style="margin: 5px 0; font-size: 0.85em; color: #888;">
                <i class="fa fa-info-circle"></i> Tip: Add emotion tags like <code>[gentle]</code> or <code>[sad]</code> directly in the transcription for fine control.
            </p>
            <div style="margin-bottom: 8px;">
                <label style="font-size: 0.9em; color: #666;">Direction:</label>
                <select id="tts-direction-select" style="padding: 4px; margin-left: 4px;">
                    <?php foreach ($direction_presets as $tag => $label): ?>
                    <option value="<?php echo escape($tag); ?>" <?php echo $tag === '[elderly, nostalgic]' ? 'selected' : ''; ?>>
                        <?php echo escape($label); ?>
                    </option>
                    <?php endforeach; ?>
                </select>
            </div>
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
        var direction = document.getElementById('tts-direction-select').value;
        var status = document.getElementById('tts-status');
        var btn = document.getElementById(force ? 'tts-regenerate-btn' : 'tts-generate-btn');
        
        btn.disabled = true;
        status.innerHTML = '<i class="fa fa-spinner fa-spin"></i> Generating (v3)...';
        
        var xhr = new XMLHttpRequest();
        var url = '<?php echo $baseurl_short; ?>plugins/tts_audio/pages/generate.php';
        var params = 'ref=' + resourceId + 
            '&voice=' + encodeURIComponent(voice) + 
            '&direction=' + encodeURIComponent(direction) +
            '&force=' + (force ? '1' : '0') + 
            '&ajax=true&<?php echo $CSRF_token_identifier; ?>=<?php echo $csrf_token; ?>';
        
        xhr.open('POST', url, true);
        xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
        
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                if (xhr.status === 200) {
                    try {
                        var response = JSON.parse(xhr.responseText);
                        if (response.success) {
                            var msg = response.message || 'Done!';
                            if (response.parts && response.parts > 1) {
                                msg += ' (' + response.parts + ' parts)';
                            }
                            status.innerHTML = '<span style="color:green;"><i class="fa fa-check"></i> ' + msg + '</span>';
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
    
    // Hide empty consent/license panels via JS (cleaner than CSS hacks)
    ?>
    <script>
    (function() {
        // Hide RecordBox panels with empty content (just "+ New" links)
        document.querySelectorAll('.RecordBox').forEach(function(box) {
            var title = box.querySelector('.Title');
            if (title) {
                var text = title.textContent.toLowerCase();
                if (text.includes('consent') || text.includes('license')) {
                    box.style.display = 'none';
                }
            }
        });
    })();
    </script>
    <?php
    
    return false; // Allow further custom panels
}
