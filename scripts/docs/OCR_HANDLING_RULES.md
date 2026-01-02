# OCR Text Handling Rules

## Archival Integrity Principles

These rules govern how OCR text is processed, stored, and displayed in ResourceSpace to maintain archival integrity while providing readable access to historical documents.

## Field Hierarchy

| Field ID | Name | Purpose | Mutability |
|----------|------|---------|------------|
| **88** | `ocrtext` | Raw OCR output | **IMMUTABLE** |
| **89** | `transcriptioncleaned` | Literal transcription | Write-once |
| **96** | `transcriptionreaderformatted` | Reader-friendly version | Iterable |

---

## Field 88: Raw OCR Text (IMMUTABLE)

### Purpose
Preserves the exact, unmodified output from the OCR engine.

### Rules
1. **NEVER modify** - This is the machine-generated source of truth
2. Include ALL text exactly as OCR produced it, including:
   - OCR errors and artifacts
   - Line breaks as detected
   - Character misrecognitions
   - Fragmented words
3. Prepend with source filename: `--- filename.pdf ---`
4. Multiple pages separated by `--- filename.pdf ---` headers

### Example
```
--- 01_intro_dear_danny_vienna_childhood.pdf ---
te
Dear Dummy
after have tryed pereral times to
"Write" my.
méinories in an unorthodox
way- fummy - cesting - good. I give up.
```

---

## Field 89: Literal Transcription (Write-Once)

### Purpose
Human-verified transcription that corrects obvious OCR errors while remaining **faithful to what was actually written**.

### Rules

1. **Correct OCR errors only** - Fix machine misreadings, NOT the author's spelling/grammar
   - ✓ "Dummy" → "Danny" (OCR misread handwriting)
   - ✓ "pereral" → "several" (OCR misread)
   - ✗ Don't "fix" author's intentional misspellings or period-appropriate language

2. **Preserve original structure**
   - Keep paragraph breaks as written
   - Preserve emphasis (underlines → *italics*)
   - Maintain original punctuation choices

3. **Mark uncertainties**
   - `[unclear]` - text is present but unreadable
   - `[illegible]` - cannot determine what was written
   - `[word?]` - best guess with uncertainty marker
   - `[...page torn...]` - physical document damage

4. **No interpretation**
   - Don't add context or explanations
   - Don't modernize language
   - Don't correct grammatical "errors" that may be period-appropriate or intentional

5. **Source reference**
   - Each section references source: `[Source: filename.pdf]`

### Example
```
[Source: 01_intro_dear_danny_vienna_childhood.pdf]

Dear Danny

After I have tried several times to "write" my memories in an 
unorthodox way - funny - jesting - good. I give up. I will just 
write facts in chronological order and then if I will still have 
time I might write a few episodes of my life.

As you know I was born in Vienna before the first world war. When 
I was one year old the war ended. That war was called the WAR to 
end all wars. Little did they know that human nature was foxy.
```

### Verification Checklist
- [ ] OCR errors corrected (comparing to original scan)
- [ ] Author's original wording preserved
- [ ] Unclear sections marked appropriately
- [ ] Paragraph structure matches original
- [ ] Source file referenced

---

## Field 96: Reader-Friendly Version (Iterable)

### Purpose
Optimized for reading comprehension while maintaining factual accuracy.

### Rules

1. **Structure for readability**
   - Add section headers
   - Group related content
   - Add contextual headers (dates, locations, topics)

2. **Maintain accuracy**
   - Content must match literal transcription
   - No adding information not in source
   - No removing significant content

3. **Permitted modifications**
   - Add section headers: `--- Topic: Description ---`
   - Light punctuation normalization
   - Paragraph grouping for flow
   - Brief contextual notes in brackets: `[referring to Vienna, 1938]`

4. **Required elements**
   - Header block identifying the collection
   - Source file references
   - Clear separation between editorial additions and source text

### Example
```
=============================================================================
OMI'S MEMOIRS - INTRODUCTIONS
=============================================================================
These pages represent Omi's various attempts to begin writing her memoirs,
addressed to "Danny" (a grandchild). She reflects on how to structure her
life story and mentions key themes: Vienna, the wars, and her philosophy
on life and memory.

Source files: 01_intro_dear_danny_vienna_childhood.pdf, 
              02_intro_how_to_begin.pdf, 
              03_vienna_dobling_leaving_hitler.pdf
=============================================================================


--- Page 1: "Dear Danny" ---
[Source: 01_intro_dear_danny_vienna_childhood.pdf]

Dear Danny

After I have tried several times to "write" my memories in an unorthodox 
way - funny - jesting - good. I give up. I will just write facts in 
chronological order and then if I will still have time I might write a 
few episodes of my life.
```

---

## Processing Workflow

```
┌─────────────────┐
│  Scanned Image  │
│   / PDF Page    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   OCR Engine    │  Google Vision / Document AI
│  (Automated)    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Field 88: RAW  │  ◄── IMMUTABLE: Never touch after initial save
│   OCR Output    │
└────────┬────────┘
         │
         ▼ (Human review)
┌─────────────────┐
│ Field 89: LITERAL│ ◄── Compare to original scan, correct OCR errors only
│  Transcription   │     Preserve author's voice and structure
└────────┬────────┘
         │
         ▼ (Editorial)
┌─────────────────┐
│Field 96: FORMATTED│ ◄── Add structure for reading
│  Reader Version   │     Maintain factual accuracy
└─────────────────┘
```

---

## Multi-Model Verification (Optional)

For high-confidence OCR, use `ocr_verify.py` to run 4 models and build consensus.

### Models Used

| Model | Type | Purpose |
|-------|------|---------|
| Document AI | Dedicated OCR | Primary OCR, best for handwriting |
| Vision API | Dedicated OCR | Secondary OCR, fast for typewritten |
| Claude Vision | LLM | Semantic verification |
| GPT-5.2 Vision | LLM | Semantic verification |

### Consensus Logic

```
4/4 agree → Very High Confidence (~99%+ accurate) → Auto-accept
3/4 agree → High Confidence (~95%+ accurate) → Accept with note
2/4 agree → Medium Confidence → Flag for human review
All differ → Low Confidence → Human decision required
```

### Tie-Breaking Priority

1. Prefer dedicated OCR engines over LLMs
2. If OCR engines disagree, majority of LLMs decides
3. If still tied, flag for human review

### Usage

```bash
# Full 4-model verification
python scripts/ocr_verify.py --image page.jpg --output consensus.txt --report report.json

# Review disagreement report
cat report.json | jq '.disagreements'
```

### When to Use

- **Archival documents** requiring maximum accuracy
- **Difficult handwriting** where single OCR might fail
- **Legal/compliance** contexts needing audit trail
- **Batch processing** where human review time is limited

### Cost Consideration

~$0.03-0.05 per page (all 4 models). For budget-conscious processing, use `--engines docai,vision` for ~$0.003/page.

---

## Quality Control

### Before Publishing Field 89 (Literal)
1. Compare side-by-side with original scan
2. Verify OCR corrections are accurate (not over-corrections)
3. Confirm unclear/illegible marks are appropriate
4. Check source file references

### Before Publishing Field 96 (Formatted)
1. Verify content matches Field 89 (no invented content)
2. Confirm editorial additions are clearly marked
3. Check section organization is logical
4. Verify all source files are referenced

---

## Common Mistakes to Avoid

### ❌ DON'T: Over-correct in Literal Transcription
```
Raw OCR: "I was very fair and my hair took all the coloured dust"
Wrong:   "I was very fair and my hair took all the colored dust"
Correct: "I was very fair and my hair took all the coloured dust"
         (British spelling is original, not an OCR error)
```

### ❌ DON'T: Add interpretation in Literal
```
Wrong:   "Danny [her grandson], I told you often..."
Correct: "Danny, I told you often..."
         (Save context for formatted version or notes)
```

### ❌ DON'T: Skip the Literal step
```
Wrong:   Raw OCR → Formatted (loses verifiable middle layer)
Correct: Raw OCR → Literal → Formatted
```

### ❌ DON'T: "Fix" the author's style
```
Original: "Little did they know that human nature was foxy."
Wrong:    "Little did they know that human nature was crafty."
Correct:  "Little did they know that human nature was foxy."
          ("foxy" is the author's word choice)
```

---

## Script Integration

### ocr.py
Single-model OCR with auto-detection. Outputs to Field 88 only.

### ocr_verify.py
Multi-model verification (4 engines). Outputs:
- Consensus text for Field 88
- Disagreement report (JSON) for audit trail
- Confidence scores per word

### transcribe_ocr.py
Claude-assisted OCR correction. Creates Field 89 (Literal) from Field 88.

### translate_ocr.py
Claude Opus 4.5 translation. Creates Field 101 (English Translation).

### sync_transcription.py
Enforces field mutability rules:
- Field 88: Refuses to overwrite existing content
- Field 89: Requires `--force-literal` to update
- Field 96: Allows updates (iterable)

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-02 | Initial rules document |
| 1.1 | 2026-01-02 | Added multi-model verification section |
