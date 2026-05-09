"""Lightweight, Pillow-only image preprocessing pipeline applied before OCR.

The goal is to lift Tesseract's accuracy on the kinds of inputs Nashr actually
sees — phone photos of textbook pages, scanned PDFs at 150–300 DPI, and small
in-PDF figures — without taking on a heavy dependency like OpenCV. Three small
moves cover the great majority of the gap:

1. Convert to grayscale: Tesseract's LSTM expects single-channel input anyway,
   and stripping color removes a class of distractions (highlights, faint
   colored watermarks).
2. Upscale very small images: Tesseract degrades sharply below ~30 px tall
   characters; small inputs are bicubically scaled by 2x using LANCZOS so the
   recognizer sees enough pixel detail.
3. Light contrast boost via autocontrast: pulls black levels down and white
   levels up so faded scans print as crisp black-on-white. We deliberately
   stop short of binarisation/thresholding — modern Tesseract already does
   adaptive thresholding internally and aggressive client-side binarisation
   can hurt more than it helps.

Deskew is intentionally out of scope for v1. Doing it well needs Hough lines
or projection profiles, which is more code and CPU than pays back here.
"""

from __future__ import annotations

from typing import Final

from PIL import Image, ImageOps

MIN_WIDTH_PX: Final[int] = 1000
UPSCALE_FACTOR: Final[int] = 2


class OCRPreprocessor:
    """Apply a fixed Pillow-only enhancement pipeline before Tesseract sees an image."""

    def preprocess(self, image: Image.Image) -> Image.Image:
        """Return a new image enhanced for OCR; the caller's image is left intact."""

        result = image
        if result.mode != "L":
            result = result.convert("L")
        if result.width < MIN_WIDTH_PX:
            new_size = (
                result.width * UPSCALE_FACTOR,
                result.height * UPSCALE_FACTOR,
            )
            result = result.resize(new_size, resample=Image.Resampling.LANCZOS)
        result = ImageOps.autocontrast(result, cutoff=2)
        return result
