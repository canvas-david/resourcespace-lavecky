<?php
/**
 * OCR Side Panel - View Page Hooks
 * 
 * Hooks into the resource view page to display OCR text alongside the image
 */

include_once dirname(__FILE__, 2) . '/include/ocr_sidepanel_functions.php';

/**
 * Hook that fires before the resource details section
 * We inject the OCR panel that will be positioned via CSS
 */
function HookOcr_sidepanelViewRenderbeforeresourcedetails()
{
    global $ref, $resource, $lang;
    
    // Check if resource has OCR text
    $ocr_text = ocr_sidepanel_get_ocr_text($ref);
    if ($ocr_text === null) {
        return false;
    }
    
    // Add class to body for CSS targeting
    ?>
    <script>document.body.classList.add('has-ocr-sidepanel');</script>
    
    <div class="ocr-sidepanel-container" id="ocr-sidepanel">
        <div class="ocr-sidepanel-panel">
            <div class="ocr-sidepanel-header">
                <h3>
                    <i class="fa fa-file-text-o"></i>
                    <?php echo isset($lang['ocr_sidepanel_title']) ? escape($lang['ocr_sidepanel_title']) : 'OCR Text (Original)'; ?>
                </h3>
                <div class="ocr-sidepanel-controls">
                    <button onclick="toggleOcrSidepanel()" id="ocr-toggle-btn" title="Toggle panel">
                        <i class="fa fa-compress" id="ocr-toggle-icon"></i>
                    </button>
                </div>
            </div>
            <div class="ocr-sidepanel-content" id="ocr-content">
                <pre><?php echo htmlspecialchars($ocr_text); ?></pre>
            </div>
        </div>
    </div>
    
    <script>
    (function() {
        // Move the OCR panel to be a sibling of RecordResource for side-by-side positioning
        var panel = document.getElementById('ocr-sidepanel');
        var recordResource = document.querySelector('.RecordResource');
        if (panel && recordResource) {
            // Create wrapper for side-by-side layout
            var wrapper = document.createElement('div');
            wrapper.className = 'ocr-sidepanel-wrapper';
            recordResource.parentNode.insertBefore(wrapper, recordResource);
            wrapper.appendChild(recordResource);
            wrapper.appendChild(panel);
        }
    })();
    
    function toggleOcrSidepanel() {
        var content = document.getElementById('ocr-content');
        var icon = document.getElementById('ocr-toggle-icon');
        var panel = document.getElementById('ocr-sidepanel');
        
        if (content.style.display === 'none') {
            content.style.display = 'block';
            icon.className = 'fa fa-compress';
            panel.classList.remove('collapsed');
        } else {
            content.style.display = 'none';
            icon.className = 'fa fa-expand';
            panel.classList.add('collapsed');
        }
    }
    </script>
    <?php
    
    return false;
}
