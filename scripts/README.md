# Scripts

OCR, transcription, and utility scripts for ResourceSpace.

## Setup

```bash
cd scripts
source .env
```

## Main Scripts

| Script | Purpose |
|--------|---------|
| `ocr.py` | Unified OCR with auto-detection (Document AI / Vision API) |
| `ocr_verify.py` | 4-model OCR verification with consensus voting |
| `transcribe_ocr.py` | Convert raw OCR to literal transcription (Claude) |
| `translate_ocr.py` | Translate OCR text (Claude Opus 4.5) |
| `sync_transcription.py` | Sync transcriptions to ResourceSpace |
| `batch_ocr.py` | Batch OCR + translation pipeline |
| `generate_tts.py` | Generate TTS audio (ElevenLabs) |
| `db.sh` | SSH database access helper |

## Directory Structure

```
scripts/
├── .env                     # Credentials (source this first)
├── gcp-service-account.json # Google Cloud service account
│
├── ocr.py                   # Main OCR
├── ocr_verify.py            # 4-model verification
├── transcribe_ocr.py        # OCR → literal transcription
├── translate_ocr.py         # Translation
├── sync_transcription.py    # Sync to ResourceSpace
├── batch_ocr.py             # Batch OCR + translation
├── generate_tts.py
├── db.sh
│
├── upload/                  # Upload utilities
│   ├── upload_testimony.py  # General testimony upload
│   └── upload_files_ssh.sh  # SSH-based file upload
│
├── archive/                 # One-off task-specific scripts
│   └── omis_letters/        # Omi's Letters upload (Jan 2026)
│
├── db/                      # Database setup
│   ├── create_ocr_fields.sql
│   ├── create_tts_fields.sql
│   └── setup_ocr_fields.sh
│
├── faces/                   # Face detection
│   ├── detect_faces.php
│   └── test_faces.sh
│
├── legacy/                  # Superseded scripts
│   ├── ocr_claude.py        # Use ocr.py instead
│   ├── ocr_google_vision.py # Use ocr.py instead
│   └── process_ocr.py       # Use ocr.py instead
│
└── docs/                    # Documentation
    ├── ARCHIVAL_API_REFERENCE.md
    ├── OCR_HANDLING_RULES.md
    └── env.example
```

## Quick Examples

```bash
# OCR a document (auto-detects best engine)
python ocr.py --file page.jpg --output ocr.txt

# 4-model verification for high confidence
python ocr_verify.py --image page.jpg --output verified.txt --report report.json

# Translate OCR text
python translate_ocr.py --input ocr.txt --source pl --output translated.txt

# Batch process documents
python batch_ocr.py --input-dir ../downloads/doc_123 --polish-pages 1-20
```

## Environment Variables

See `docs/env.example` for all required variables:

- `GOOGLE_API_KEY` - Vision API
- `GOOGLE_APPLICATION_CREDENTIALS` - Document AI
- `ANTHROPIC_API_KEY` - Claude
- `OPENAI_API_KEY` - GPT-4o
- `RS_API_KEY` - ResourceSpace API
- `ELEVENLABS_API_KEY` - TTS
