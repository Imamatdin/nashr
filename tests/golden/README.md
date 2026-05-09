# Golden test files

Each file in this directory is a deterministic input fixture used by the test
suite. They are NOT real user content; they are crafted to exercise specific
behaviors of the source-processing pipeline.

Generate or refresh them via:

```
python scripts/generate_golden.py
```

| File | What it tests |
|------|---------------|
| `sample_3page.pdf` | Basic multi-page PDF parsing. Latin-script Uzbek with `o'` and `g'` characters across 3 pages, ≥200 words/page. Used to verify PDF text extraction, chunking, and language detection. |
| `sample_scanned.png` | OCR path. A PNG that *looks* like a scanned typed page, with mixed Uzbek + Russian text. Used to verify Tesseract OCR with `uzb+rus+eng` traineddata. |
| `sample_article.docx` | DOCX parsing. Referat structure (Kirish, Asosiy qism, Xulosa, Adabiyotlar) with headings and body paragraphs. |
| `prompt_injection.pdf` | Security regression. Page 2 contains an instruction-injection payload ("IGNORE ALL PREVIOUS INSTRUCTIONS..."). Pipeline must wrap content as data and refuse to follow it. |
| `empty.pdf` | Edge case. Valid PDF with no extractable text. Pipeline must reject gracefully, not crash. |
| `sample_with_doi.pdf` | DOI auto-resolution. PDF whose metadata contains a DOI; pipeline must extract it and resolve via CrossRef. |

Do not edit the binary files by hand — re-run the generator to keep checksums
deterministic.
