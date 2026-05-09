"""Per-format parsers used by the source-processing worker."""

from packages.workers.source.parsers.docx_parser import DOCXParser
from packages.workers.source.parsers.image_parser import ImageParser
from packages.workers.source.parsers.lang_detect import detect_language
from packages.workers.source.parsers.pdf_parser import PDFParser
from packages.workers.source.parsers.pptx_parser import PPTXParser
from packages.workers.source.parsers.text_parser import TextParser
from packages.workers.source.parsers.xlsx_parser import XLSXParser

__all__ = [
    "DOCXParser",
    "ImageParser",
    "PDFParser",
    "PPTXParser",
    "TextParser",
    "XLSXParser",
    "detect_language",
]
