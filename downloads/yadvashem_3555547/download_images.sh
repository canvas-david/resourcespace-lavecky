#!/bin/bash
# Download images from Yad Vashem document 3555547
# "Testimony of Samuel Rozenbaum Kostman, born in Boryslaw, Poland, 1908"

BASE_URL="https://assets.yadvashem.org/image/upload"
# Remove t_f_low_image to get full resolution, keep f_auto for best format
TRANSFORM="f_auto"
PATH_PREFIX="v1/remote_media/documentation4/1/full_pdf_srika/3555547_03061968/0001"

# Image pages (00001 to 00020)
for i in $(seq -w 1 20); do
    filename="00${i}.jpg"
    url="${BASE_URL}/${TRANSFORM}/${PATH_PREFIX}/${filename}"
    output="page_${i}.jpg"
    
    echo "Downloading page ${i}..."
    curl -s -o "$output" "$url"
    
    if [ $? -eq 0 ] && [ -s "$output" ]; then
        echo "  ✓ Saved as $output"
    else
        echo "  ✗ Failed to download $url"
    fi
done

echo ""
echo "Download complete! Files saved to: $(pwd)"
ls -la *.jpg 2>/dev/null | wc -l | xargs -I {} echo "Total images downloaded: {}"
