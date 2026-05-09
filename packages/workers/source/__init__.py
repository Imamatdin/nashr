"""Source-processing worker: file validation (Magika), parsing, OCR, chunking, claim extraction."""

from packages.workers.source.parse_service import SourceParseService
from packages.workers.source.parsers import (
    DOCXParser,
    ImageParser,
    PDFParser,
    PPTXParser,
    TextParser,
    XLSXParser,
    detect_language,
)
from packages.workers.source.validation import EXTENSION_MAP, FileValidationService

__all__ = [
    "EXTENSION_MAP",
    "DOCXParser",
    "FileValidationService",
    "ImageParser",
    "PDFParser",
    "PPTXParser",
    "SourceParseService",
    "TextParser",
    "XLSXParser",
    "detect_language",
]
