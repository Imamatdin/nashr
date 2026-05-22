"""Project-wide numeric and set constants.

These values are referenced by validators, services, workers, and database checks.
Changing one here must be matched everywhere.
"""

from __future__ import annotations

from typing import Final

from packages.core.enums import FileType, JobType

MAX_FILE_SIZE_BYTES: Final[int] = 20_971_520

MAX_FILES_PER_PROJECT: Final[int] = 10

MAX_STORAGE_PER_USER_BYTES: Final[int] = 209_715_200

MAX_SLIDES: Final[int] = 20
MIN_SLIDES: Final[int] = 3

MAX_TITLE_LENGTH: Final[int] = 70
MAX_SUBTITLE_LENGTH: Final[int] = 130
MAX_BODY_ITEM_LENGTH: Final[int] = 120
MAX_BODY_ITEMS: Final[int] = 4

MIN_FONT_SIZE_BODY: Final[int] = 18
MIN_FONT_SIZE_TITLE: Final[int] = 36

MAX_WORDS_PER_CONTENT_SLIDE: Final[int] = 50

MIN_NEGATIVE_SPACE_RATIO: Final[float] = 0.30

MIN_CONTRAST_RATIO: Final[float] = 4.5

CREDIT_CAPS: Final[dict[str, int]] = {
    "daily": 3,
    "weekly": 10,
    "per_project": 5,
}

FREE_CREDIT_EXPIRY_DAYS: Final[int] = 90

JOB_COST_LIMITS: Final[dict[JobType, float]] = {
    JobType.SOURCE_PROCESSING: 0.20,
    JobType.PRESENTATION_GENERATION: 0.90,
    JobType.ARTICLE_GENERATION: 1.50,
    JobType.EXPORT: 0.05,
}

PACKAGE_COST_LIMITS_USD: Final[dict[str, float]] = {
    "presentation_basic": 0.20,
    "presentation_standard": 0.40,
    "presentation_premium": 0.90,
    "article_short": 0.80,
    "article_standard": 1.50,
    "research_package": 4.00,
}

ALLOWED_FILE_TYPES: Final[frozenset[str]] = frozenset({member.value for member in FileType})

BLOCKED_FILE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "javascript",
        "python",
        "shell",
        "batch",
        "html",
        "xml",
        "executable",
        "elf",
        "pe",
        "mach_o",
        "dex",
        "java_class",
        "powershell",
        "vbscript",
        "perl",
        "ruby",
        "php",
        "lua",
    }
)

MAGIKA_MIN_CONFIDENCE: Final[float] = 0.70

DAILY_GENERATION_JOB_LIMIT: Final[int] = 10

DEFAULT_LLM_TIMEOUT_SECONDS: Final[int] = 180
DEFAULT_LLM_MAX_RETRIES: Final[int] = 2

MODEL_ROUTING: Final[dict[str, str]] = {
    "citation_verification": "gemini-3-flash",
    "claim_extraction": "gemini-3-flash",
    "answer_scoring": "gemini-3-flash",
    "question_generation": "gemini-3-flash",
    "section_drafting": "claude-sonnet-4-6-20250514",
    "outline_generation": "claude-sonnet-4-6-20250514",
    "design_direction": "claude-sonnet-4-6-20250514",
    "layout_pass": "claude-sonnet-4-6-20250514",
}

EXPORT_URL_EXPIRY_SECONDS: Final[int] = 60 * 60 * 24 * 7

PRESENTATION_TIER_IMAGE_LIMITS: Final[dict[str, int]] = {
    "presentation_basic": 0,
    "presentation_standard": 2,
    "presentation_premium": 5,
}

PRICING_UZS: Final[dict[str, int]] = {
    "presentation_basic": 5_000,
    "presentation_standard": 10_000,
    "presentation_premium": 15_000,
    "article_short": 60_000,
    "article_standard": 95_000,
    "research_package": 150_000,
    "bundle_article_presentation": 135_000,
}

OCR_LANGUAGES: Final[tuple[str, ...]] = ("uzb", "rus", "eng")

UZBEK_DOCX_FORMAT: Final[dict[str, float | int | str]] = {
    "font_name": "Times New Roman",
    "font_size_pt": 14,
    "line_spacing": 1.5,
    "margin_top_cm": 2.0,
    "margin_bottom_cm": 2.0,
    "margin_left_cm": 3.0,
    "margin_right_cm": 1.5,
}

assert ALLOWED_FILE_TYPES.isdisjoint(BLOCKED_FILE_TYPES), (
    "ALLOWED_FILE_TYPES and BLOCKED_FILE_TYPES must not overlap"
)
