<?php
/**
 * OCR Side Panel - All Pages Hooks
 * 
 * Hooks that run on all pages
 */

include_once dirname(__FILE__, 2) . '/include/ocr_sidepanel_functions.php';

/**
 * Hook to add CSS to the page header on all pages
 */
function HookOcr_sidepanelAllPagetop()
{
    global $baseurl, $css_reload_key, $pagename;
    
    if ($pagename !== 'view') {
        return false;
    }
    ?>
    <link rel="stylesheet" href="<?php echo $baseurl; ?>/plugins/ocr_sidepanel/css/ocr_sidepanel.css?v=<?php echo $css_reload_key; ?>">
    <?php
    return false;
}
