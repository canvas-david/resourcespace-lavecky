<?php
/**
 * TTS Audio Plugin Setup Page
 * 
 * Configuration page for the TTS Audio plugin
 */

include '../../../include/boot.php';
include '../../../include/authenticate.php';

if (!checkperm('a')) {
    exit('Permission denied');
}

include_once dirname(__FILE__, 2) . '/include/tts_audio_functions.php';

// Handle form submission
$saved = false;
if (getval('save', '') !== '' && enforcePostRequest(false)) {
    // Save configuration options
    set_config_option([], 'tts_audio_default_voice', getval('tts_audio_default_voice', 'rachel'));
    set_config_option([], 'tts_audio_python_path', getval('tts_audio_python_path', 'python3'));
    set_config_option([], 'tts_audio_script_path', getval('tts_audio_script_path', ''));
    $saved = true;
}

// Get current configuration
$default_voice = 'rachel';
$python_path = 'python3';
$script_path = '';
get_config_option([], 'tts_audio_default_voice', $default_voice, 'rachel');
get_config_option([], 'tts_audio_python_path', $python_path, 'python3');
get_config_option([], 'tts_audio_script_path', $script_path, '');

include '../../../include/header.php';
?>

<div class="BasicsBox">
    <h1><?php echo $lang['tts_audio_setup'] ?? 'TTS Audio Configuration'; ?></h1>
    
    <?php if ($saved): ?>
    <div class="FormError" style="background: #d4edda; color: #155724; border-color: #c3e6cb;">
        <?php echo $lang['tts_audio_saved'] ?? 'Configuration saved successfully.'; ?>
    </div>
    <?php endif; ?>
    
    <form method="post" action="<?php echo $baseurl_short; ?>plugins/tts_audio/pages/setup.php">
        <?php generateFormToken('tts_audio_setup'); ?>
        
        <div class="Question">
            <label for="tts_audio_default_voice"><?php echo $lang['tts_audio_default_voice'] ?? 'Default Voice'; ?></label>
            <select name="tts_audio_default_voice" id="tts_audio_default_voice" class="stdwidth">
                <?php foreach (tts_audio_get_voice_options() as $id => $name): ?>
                <option value="<?php echo escape($id); ?>" <?php echo $default_voice === $id ? 'selected' : ''; ?>>
                    <?php echo escape($name); ?>
                </option>
                <?php endforeach; ?>
            </select>
            <div class="clearerleft"></div>
        </div>
        
        <div class="Question">
            <label for="tts_audio_python_path"><?php echo $lang['tts_audio_python_path'] ?? 'Python Path'; ?></label>
            <input type="text" name="tts_audio_python_path" id="tts_audio_python_path" 
                   class="stdwidth" value="<?php echo escape($python_path); ?>"
                   placeholder="python3">
            <div class="FormHelp"><?php echo $lang['tts_audio_python_help'] ?? 'Path to Python 3 executable (e.g., python3, /usr/bin/python3)'; ?></div>
            <div class="clearerleft"></div>
        </div>
        
        <div class="Question">
            <label for="tts_audio_script_path"><?php echo $lang['tts_audio_script_path'] ?? 'Script Path'; ?></label>
            <input type="text" name="tts_audio_script_path" id="tts_audio_script_path" 
                   class="stdwidth" value="<?php echo escape($script_path); ?>"
                   placeholder="/path/to/scripts/generate_tts.py">
            <div class="FormHelp"><?php echo $lang['tts_audio_script_help'] ?? 'Full path to generate_tts.py script. Leave empty to use default location.'; ?></div>
            <div class="clearerleft"></div>
        </div>
        
        <div class="Question">
            <label><?php echo $lang['tts_audio_env_vars'] ?? 'Required Environment Variables'; ?></label>
            <div class="Fixed" style="font-family: monospace; font-size: 12px; background: #f8f9fa; padding: 10px; border-radius: 4px;">
                ELEVENLABS_API_KEY=your_api_key<br>
                RS_API_KEY=your_resourcespace_api_key<br>
                RS_BASE_URL=<?php echo $baseurl; ?><br>
                RS_USER=admin
            </div>
            <div class="FormHelp"><?php echo $lang['tts_audio_env_help'] ?? 'These environment variables must be set on the server for TTS generation to work.'; ?></div>
            <div class="clearerleft"></div>
        </div>
        
        <div class="QuestionSubmit">
            <input type="submit" name="save" value="<?php echo $lang['save'] ?? 'Save'; ?>">
        </div>
    </form>
</div>

<?php
include '../../../include/footer.php';
