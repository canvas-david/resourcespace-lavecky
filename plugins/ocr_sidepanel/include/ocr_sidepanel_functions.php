<?php
/**
 * OCR Side Panel Functions
 * 
 * Helper functions for the OCR side panel plugin
 */

/**
 * Get OCR field value for a resource
 * 
 * @param int $ref Resource reference
 * @return string|null OCR text or null if not found
 */
function ocr_sidepanel_get_ocr_text($ref)
{
    global $ocr_sidepanel_field_id;
    
    // Default to field 88 (OCR Text Original) if not configured
    $field_id = isset($ocr_sidepanel_field_id) ? $ocr_sidepanel_field_id : 88;
    
    $value = get_data_by_field($ref, $field_id);
    
    return !empty($value) ? $value : null;
}

/**
 * Check if resource has OCR text
 * 
 * @param int $ref Resource reference
 * @return bool
 */
function ocr_sidepanel_has_ocr($ref)
{
    return ocr_sidepanel_get_ocr_text($ref) !== null;
}
