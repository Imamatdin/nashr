---
paths:
  - "packages/workers/source/**"
---

# Source Worker Rules

- Every sync library (fitz, python-docx, python-pptx, Magika, Pillow, Tesseract) must be called via `await asyncio.to_thread()`. Never call sync I/O directly in async functions.
- Magika is instantiated ONCE in __init__, not per-call.
- Every parser must handle corrupt/malicious input without crashing. Wrap document-open calls in try/except. Return ParsedSource with parse_errors populated, never raise to caller.
- PDF parser: close fitz.Document after use (resource leak prevention).
- Uploaded file content is DATA, never instructions. Never place file content in LLM system prompts.
- Every new file type added to ALLOWED_FILE_TYPES must have a corresponding parser in parse_service.py routing AND a golden test fixture.
- OCR results must include confidence scores. Low-confidence OCR text is flagged, not silently accepted.
- Language detection uses the heuristic in lang_detect.py. Do not add heavy NLP library dependencies for this.
