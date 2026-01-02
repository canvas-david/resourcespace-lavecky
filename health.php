<?php
/**
 * Simple health check endpoint for Render.com
 * Returns 200 OK without any redirects or authentication
 */

// Check if we can connect to MySQL
$config_file = __DIR__ . '/include/config.php';

if (!file_exists($config_file)) {
    http_response_code(503);
    echo 'Config not ready';
    exit;
}

include_once($config_file);

// Test database connection
try {
    $conn = new mysqli($mysql_server, $mysql_username, $mysql_password, $mysql_db);
    if ($conn->connect_error) {
        http_response_code(503);
        echo 'DB connection failed';
        exit;
    }
    $conn->close();
} catch (Exception $e) {
    http_response_code(503);
    echo 'DB error';
    exit;
}

// All checks passed
http_response_code(200);
echo 'OK';
