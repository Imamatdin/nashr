"""Source-processing worker: file validation (Magika), parsing, OCR, chunking, claim extraction."""

from packages.workers.source.chunker import SourceChunker
from packages.workers.source.claim_extractor import ClaimExtractor
from packages.workers.source.ocr import OCRService
from packages.workers.source.ocr_preprocess import OCRPreprocessor
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
from packages.workers.source.pipeline import SourcePipeline
from packages.workers.source.validation import EXTENSION_MAP, FileValidationService

__all__ = [
    "EXTENSION_MAP",
    "ClaimExtractor",
    "DOCXParser",
    "FileValidationService",
    "ImageParser",
    "OCRPreprocessor",
    "OCRService",
    "PDFParser",
    "PPTXParser",
    "SourceChunker",
    "SourceParseService",
    "SourcePipeline",
    "TextParser",
    "XLSXParser",
    "detect_language",
]
