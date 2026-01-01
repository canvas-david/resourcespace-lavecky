#!/usr/bin/env php
<?php
/**
 * Trigger face detection on a ResourceSpace resource.
 * 
 * Usage: php detect_faces.php <resource_id>
 * 
 * Run from ResourceSpace container:
 *   php /var/www/html/scripts/detect_faces.php 1
 */

// Bootstrap ResourceSpace
$webroot = '/var/www/html';
chdir($webroot);

include_once "$webroot/include/boot.php";
include_once "$webroot/include/authenticate.php";
include_once "$webroot/include/resource_functions.php";
include_once "$webroot/plugins/faces/include/faces_functions.php";

// Get resource ID from args
$resource_id = isset($argv[1]) ? (int)$argv[1] : 1;

echo "==> Faces Plugin Configuration\n";
echo "Service endpoint: " . ($faces_service_endpoint ?? 'NOT SET') . "\n";
echo "Confidence threshold: " . ($faces_confidence_threshold ?? 'NOT SET') . "\n";
echo "\n";

// Check if faces plugin is active
if (!function_exists('faces_detect')) {
    echo "ERROR: Faces plugin not loaded. Enable it in Admin > System > Plugins\n";
    exit(1);
}

// Check service endpoint
if (empty($faces_service_endpoint)) {
    echo "ERROR: \$faces_service_endpoint not configured.\n";
    echo "Add to config.php or plugin settings:\n";
    echo "  \$faces_service_endpoint = 'http://faces-d1tp:10000';\n";
    exit(1);
}

// Test service connectivity
echo "==> Testing faces service at $faces_service_endpoint\n";
$ch = curl_init("$faces_service_endpoint/");
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 5);
curl_exec($ch);
$http_code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);
echo "Service response: HTTP $http_code\n\n";

// Check resource exists
echo "==> Checking resource $resource_id\n";
$resource = get_resource_data($resource_id);
if (!$resource) {
    echo "ERROR: Resource $resource_id not found\n";
    exit(1);
}
echo "Resource type: " . $resource['resource_type'] . "\n";
echo "File extension: " . $resource['file_extension'] . "\n";
echo "Faces processed: " . ($resource['faces_processed'] ?? 'unknown') . "\n\n";

// Find the image file
$file_path = get_resource_path($resource_id, true, 'scr', false, "jpg");
if (!file_exists($file_path)) {
    $file_path = get_resource_path($resource_id, true, '', false, $resource['file_extension']);
}
echo "Image path: $file_path\n";
echo "File exists: " . (file_exists($file_path) ? "YES" : "NO") . "\n\n";

if (!file_exists($file_path)) {
    echo "ERROR: No image file found for resource $resource_id\n";
    exit(1);
}

// Reset faces_processed flag to allow re-detection
echo "==> Resetting faces_processed flag\n";
ps_query("UPDATE resource SET faces_processed = 0 WHERE ref = ?", ["i", $resource_id]);

// Run face detection
echo "==> Running face detection on resource $resource_id\n";
$result = faces_detect($resource_id);

if ($result) {
    echo "\n==> SUCCESS\n";
    
    // Show detected faces
    $faces = ps_query("SELECT ref, bbox, det_score FROM resource_face WHERE resource = ?", ["i", $resource_id]);
    echo "Detected " . count($faces) . " face(s):\n";
    foreach ($faces as $face) {
        echo "  Face #{$face['ref']}: score={$face['det_score']}, bbox={$face['bbox']}\n";
    }
} else {
    echo "\n==> Face detection returned false (may be no faces found or already processed)\n";
}
