# Omi's Letters - OCR Processing

Handwritten letters from Omi (grandmother) documenting family history from Vienna through WWII to Australia.

## Directory Structure

```
Omi's letters/
├── source/                    # Original PDF scans (10 documents)
├── images/                    # Extracted page images (300 DPI PNG)
├── ocr_verified/              # Multi-model verified OCR output
├── transcription/
│   ├── literal/               # Faithful transcriptions (Field 89)
│   └── formatted/             # Reader-friendly versions (Field 96)
├── reports/                   # Verification reports (JSON)
├── archive/
│   ├── ocr_v1/                # Previous OCR attempt
│   └── organized_v1/          # Previous organization
└── extract_pages.py           # PDF to image extraction script
```

## Document Index

| # | Filename | Content |
|---|----------|---------|
| 01 | intro_dear_danny_vienna_childhood | Opening letter to Danny, Vienna childhood memories |
| 02 | intro_how_to_begin | Memoir introduction, where to begin |
| 03 | vienna_dobling_leaving_hitler | Vienna/Döbling district, leaving due to Hitler |
| 04 | vienna_cultural_life_composers | Vienna cultural life, composers |
| 05 | cairo_vily_illness_heat | Cairo, Vily's illness, the heat |
| 06 | 1942_el_alamein_escape_luxor | 1942 El Alamein, escape to Luxor |
| 07 | path_to_australia_mrs_lavecky | Journey to Australia, Mrs Lavecky |
| 08 | 1977_karen_birth_family | 1977, Karen's birth, family |
| 09 | grandchildren_blue_mountains_diary | Grandchildren, Blue Mountains, diary |
| 10 | blue_mountains_health_reflections | Blue Mountains, health, reflections |

## Processing Pipeline

### Step 1: Multi-Model OCR Verification

```bash
cd /Users/vex/CodeLocal/ResourceSpace/scripts
source .env

# Run 4-model verification on all images
python ocr_verify.py \
    --input-dir "../Omi's letters/images" \
    --output-dir "../Omi's letters/ocr_verified" \
    --report-dir "../Omi's letters/reports"
```

### Step 2: Create Literal Transcriptions

```bash
# For each verified OCR, create literal transcription with image verification
for img in "../Omi's letters/images"/*.png; do
    name=$(basename "$img" .png)
    python transcribe_ocr.py \
        --ocr "../Omi's letters/ocr_verified/${name}_consensus.txt" \
        --scan "$img" \
        --output "../Omi's letters/transcription/literal/${name}.txt"
done
```

### Step 3: Sync to ResourceSpace

```bash
# Sync each document (example for document 01)
python sync_transcription.py \
    --resource-id <ID> \
    --ocr "../Omi's letters/ocr_verified/01_..._consensus.txt" \
    --literal "../Omi's letters/transcription/literal/01_....txt" \
    --lang en \
    --version v2.0.0
```

## Notes

- **Handwritten content**: These are personal handwritten letters, requiring Document AI for primary OCR
- **Language**: English (Australian English)
- **Multi-model verification**: Uses Document AI + Vision API + Claude + GPT-4o for consensus
- **Archive**: Previous OCR in `archive/ocr_v1/` preserved for comparison
