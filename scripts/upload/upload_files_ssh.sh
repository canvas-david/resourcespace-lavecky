#!/bin/bash
# Upload PDF files to ResourceSpace via SSH/SCP
# Usage: ./upload_files_ssh.sh

set -e

SSH_HOST="srv-d5acinkhg0os73cr9gq0@ssh.oregon.render.com"
LETTERS_DIR="/Users/vex/CodeLocal/ResourceSpace/Omi's letters"
REMOTE_TMP="/tmp/omis_letters"

echo "=== Uploading Omi's Letters PDFs to ResourceSpace ==="
echo ""

# Create remote temp directory
echo "Creating remote temp directory..."
ssh -o StrictHostKeyChecking=no "$SSH_HOST" "mkdir -p $REMOTE_TMP"

# Upload all PDFs
echo "Uploading PDFs..."
for pdf in "$LETTERS_DIR"/*.pdf; do
    filename=$(basename "$pdf")
    echo "  Uploading: $filename"
    scp -o StrictHostKeyChecking=no -q "$pdf" "$SSH_HOST:$REMOTE_TMP/$filename"
done

echo ""
echo "Importing files into ResourceSpace..."

# Create and run PHP import script
ssh -o StrictHostKeyChecking=no "$SSH_HOST" "cat > $REMOTE_TMP/import.php" << 'PHPEOF'
<?php
// Import uploaded PDFs into ResourceSpace
error_reporting(E_ALL);
ini_set('display_errors', 1);

// Bootstrap ResourceSpace
include "/var/www/html/include/boot.php";

$tmp_dir = "/tmp/omis_letters";

// Resource -> Primary PDF mapping
$primary_pdfs = [
    9 => "01_intro_dear_danny_vienna_childhood.pdf",
    10 => "04_vienna_cultural_life_composers.pdf",
    11 => "05_cairo_vily_illness_heat.pdf",
    12 => "08_1977_karen_birth_family.pdf",
];

// Resource -> Alt PDFs mapping
$alt_pdfs = [
    9 => ["02_intro_how_to_begin.pdf", "03_vienna_dobling_leaving_hitler.pdf"],
    11 => ["06_1942_el_alamein_escape_luxor.pdf", "07_path_to_australia_mrs_lavecky.pdf"],
    12 => ["09_grandchildren_blue_mountains_diary.pdf", "10_blue_mountains_health_reflections.pdf"],
];

foreach ($primary_pdfs as $ref => $pdf) {
    $source = "$tmp_dir/$pdf";
    if (!file_exists($source)) {
        echo "ERROR: $pdf not found\n";
        continue;
    }
    
    echo "Importing $pdf to resource $ref...\n";
    
    // Get target path
    $ext = pathinfo($pdf, PATHINFO_EXTENSION);
    $target = get_resource_path($ref, true, "", true, $ext);
    
    // Ensure directory exists
    $target_dir = dirname($target);
    if (!is_dir($target_dir)) {
        mkdir($target_dir, 0777, true);
    }
    
    // Copy file
    if (copy($source, $target)) {
        chmod($target, 0664);
        
        // Update resource record
        sql_query("UPDATE resource SET file_extension='$ext', preview_extension='$ext', has_image=1 WHERE ref=$ref");
        
        // Create previews
        create_previews($ref, false, $ext);
        
        echo "  OK: $pdf -> resource $ref\n";
    } else {
        echo "  FAILED: Could not copy $pdf\n";
    }
}

// Now handle alternative files
foreach ($alt_pdfs as $ref => $pdfs) {
    foreach ($pdfs as $pdf) {
        $source = "$tmp_dir/$pdf";
        if (!file_exists($source)) {
            echo "ERROR: $pdf not found\n";
            continue;
        }
        
        echo "Adding alt file $pdf to resource $ref...\n";
        
        $ext = pathinfo($pdf, PATHINFO_EXTENSION);
        $size = filesize($source);
        $name = pathinfo($pdf, PATHINFO_FILENAME);
        
        // Create alternative file record
        $alt_ref = add_alternative_file($ref, $name, "", $pdf, $ext, $size, "");
        
        if ($alt_ref) {
            // Get target path for alt file
            $target = get_resource_path($ref, true, "", true, $ext, -1, 1, false, "", $alt_ref);
            
            // Ensure directory exists
            $target_dir = dirname($target);
            if (!is_dir($target_dir)) {
                mkdir($target_dir, 0777, true);
            }
            
            if (copy($source, $target)) {
                chmod($target, 0664);
                echo "  OK: $pdf -> alt file $alt_ref\n";
            } else {
                echo "  FAILED: Could not copy alt file $pdf\n";
            }
        } else {
            echo "  FAILED: Could not create alt file record for $pdf\n";
        }
    }
}

echo "\nDone!\n";
PHPEOF

# Run the import script
echo ""
ssh -o StrictHostKeyChecking=no "$SSH_HOST" "cd /var/www/html && php $REMOTE_TMP/import.php"

# Cleanup
echo ""
echo "Cleaning up..."
ssh -o StrictHostKeyChecking=no "$SSH_HOST" "rm -rf $REMOTE_TMP"

echo ""
echo "=== Upload Complete ==="
