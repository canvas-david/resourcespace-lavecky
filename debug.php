<?php
/**
 * Debug endpoint - shows PHP errors and config info
 * DELETE THIS FILE AFTER DEBUGGING
 */

// Enable error display
ini_set('display_errors', 1);
error_reporting(E_ALL);

echo "<pre>\n";
echo "=== PHP Debug Info ===\n\n";

// Check config file
$config_file = __DIR__ . '/include/config.php';
echo "Config file exists: " . (file_exists($config_file) ? "YES" : "NO") . "\n";

if (file_exists($config_file)) {
    echo "\n=== Config File Contents (first 50 lines) ===\n";
    $lines = file($config_file);
    $count = 0;
    foreach ($lines as $line) {
        // Hide sensitive values
        if (strpos($line, 'scramble_key') !== false) {
            echo '$scramble_key = \'[HIDDEN]\';' . "\n";
        } elseif (strpos($line, 'password') !== false) {
            echo '$mysql_password = \'[HIDDEN]\';' . "\n";
        } else {
            echo htmlspecialchars($line);
        }
        $count++;
        if ($count >= 50) break;
    }
}

echo "\n=== Attempting to include config ===\n";
try {
    include_once($config_file);
    echo "Config loaded successfully\n";
    echo "baseurl = " . (isset($baseurl) ? $baseurl : "NOT SET") . "\n";
    echo "mysql_server = " . (isset($mysql_server) ? $mysql_server : "NOT SET") . "\n";
} catch (Exception $e) {
    echo "Exception: " . $e->getMessage() . "\n";
}

echo "\n=== Attempting to include db.php ===\n";
try {
    include_once(__DIR__ . '/include/db.php');
    echo "db.php loaded successfully\n";
} catch (Exception $e) {
    echo "Exception: " . $e->getMessage() . "\n";
}

echo "\n=== PHP Version ===\n";
echo phpversion() . "\n";

echo "</pre>\n";
