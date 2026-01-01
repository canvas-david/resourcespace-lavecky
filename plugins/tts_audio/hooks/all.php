<?php
/**
 * TTS Audio - All Pages Hooks
 * 
 * Hooks that run on all pages
 */

include_once dirname(__FILE__, 2) . '/include/tts_audio_functions.php';

/**
 * Hook to add CSS to the page header on all pages
 */
function HookTts_audioAllPagetop()
{
    global $baseurl, $css_reload_key, $pagename;
    
    if ($pagename !== 'view') {
        return false;
    }
    ?>
    <link rel="stylesheet" href="<?php echo $baseurl; ?>/plugins/tts_audio/css/tts_audio.css?v=<?php echo $css_reload_key; ?>">
    <?php
    return false;
}
