"""Enums shared across all Nashr modules.

Every string-valued constant that participates in a database column or pydantic
field lives here. Values are stable wire-format identifiers and must not change
without a migration.
"""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    """User-facing language codes."""

    UZ = "uz"
    RU = "ru"
    EN = "en"


class Audience(StrEnum):
    """Target audience selected by the user before generation."""

    TALABA = "talaba"
    OQITUVCHI = "oqituvchi"
    AKADEMIK = "akademik"
    BIZNES = "biznes"


class ProjectType(StrEnum):
    """Top-level project kind."""

    PRESENTATION = "presentation"
    ARTICLE = "article"
    RESEARCH_PACKAGE = "research_package"


class ProjectStatus(StrEnum):
    """Lifecycle state of a project."""

    DRAFT = "draft"
    SOURCING = "sourcing"
    INTERVIEW = "interview"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    ARCHIVED = "archived"


class ArticleStructure(StrEnum):
    """Uzbek academic article formats."""

    REFERAT = "referat"
    KURS_ISHI = "kurs_ishi"
    ILMIY_MAQOLA = "ilmiy_maqola"
    HISOBOT = "hisobot"


class CitationFormat(StrEnum):
    """Bibliography style supported by the article worker."""

    GOST = "gost"
    APA = "apa"
    IEEE = "ieee"


class ArticleSectionStatus(StrEnum):
    """Drafting state of one article section."""

    DRAFT = "draft"
    VERIFIED = "verified"
    REVISED = "revised"
    FINAL = "final"


class SlideType(StrEnum):
    """All slide kinds the presentation pipeline can emit."""

    TITLE = "title"
    SECTION_DIVIDER = "section_divider"
    CONTENT = "content"
    TIMELINE = "timeline"
    COMPARISON = "comparison"
    DATA_STAT = "data_stat"
    QUOTE = "quote"
    BIBLIOGRAPHY = "bibliography"
    CLOSING = "closing"
    QUIZ_MCQ = "quiz_mcq"
    QUIZ_MATCHING = "quiz_matching"
    QUIZ_CATEGORIZE = "quiz_categorize"
    QUIZ_FILL_BLANK = "quiz_fill_blank"
    QUIZ_TRUE_FALSE = "quiz_true_false"
    DEBATE_SCENARIO = "debate_scenario"


class LayoutMode(StrEnum):
    """Per-slide layout mode chosen during the Layout Pass."""

    FULL_BLEED = "full_bleed"
    SPLIT_LEFT = "split_left"
    SPLIT_RIGHT = "split_right"
    CENTERED = "centered"
    GRID_CARDS = "grid_cards"
    STAT_HERO = "stat_hero"
    QUOTE = "quote"
    QUIZ = "quiz"
    MATCHING = "matching"


class BackgroundType(StrEnum):
    """How a slide background is rendered."""

    SOLID = "solid"
    GRADIENT = "gradient"
    TEXTURE = "texture"
    PATTERN = "pattern"
    IMAGE = "image"


class JobType(StrEnum):
    """Background-job kinds tracked in generation_jobs."""

    SOURCE_PROCESSING = "source_processing"
    ARTICLE_GENERATION = "article_generation"
    PRESENTATION_GENERATION = "presentation_generation"
    EXPORT = "export"


class JobStatus(StrEnum):
    """Job lifecycle states."""

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CreditReason(StrEnum):
    """Why a credit_ledger row was written."""

    PAYMENT = "payment"
    PRESENTATION_GENERATION = "presentation_generation"
    ARTICLE_GENERATION = "article_generation"
    LEARNING_REWARD = "learning_reward"
    REFUND = "refund"


class CreditStatus(StrEnum):
    """Status of an individual credit_ledger entry."""

    CONFIRMED = "confirmed"
    RESERVED = "reserved"
    REFUNDED = "refunded"


class OrderStatus(StrEnum):
    """Payment-order lifecycle."""

    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentProvider(StrEnum):
    """Supported Uzbek payment providers."""

    PAYME = "payme"
    CLICK = "click"


class SourceQuality(StrEnum):
    """Quality classification assigned during source processing."""

    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    INVALID = "invalid"


class FileType(StrEnum):
    """Magika-derived file labels accepted by the upload pipeline."""

    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    GIF = "gif"
    TXT = "txt"
    MARKDOWN = "markdown"
    CSV = "csv"


class ClaimStrength(StrEnum):
    """Strength of a single source claim."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


class CitationStatus(StrEnum):
    """State of a single evidence_matrix row."""

    READY = "ready"
    NEEDS_USER_INPUT = "needs_user_input"
    UNSUPPORTED = "unsupported"
    VERIFIED = "verified"


class ResearchQuestionType(StrEnum):
    """Categories of question posed during the research interview."""

    THESIS_CLARITY = "thesis_clarity"
    SOURCE_COVERAGE = "source_coverage"
    ORIGINALITY = "originality"
    CONTRADICTION = "contradiction"


class PrimaryUse(StrEnum):
    """Self-reported primary reason a user signed up."""

    STUDY = "study"
    TEACHING = "teaching"
    RESEARCH = "research"
    BUSINESS = "business"
    OTHER = "other"


class AcademicAPI(StrEnum):
    """Academic-search providers federated by :class:`AcademicSearchService`."""

    SEMANTIC_SCHOLAR = "semantic_scholar"
    ARXIV = "arxiv"
    OPENALEX = "openalex"
    CROSSREF = "crossref"


class GenerationPackage(StrEnum):
    """Pricing tiers offered to the user."""

    PRESENTATION_BASIC = "presentation_basic"
    PRESENTATION_STANDARD = "presentation_standard"
    PRESENTATION_PREMIUM = "presentation_premium"
    ARTICLE_SHORT = "article_short"
    ARTICLE_STANDARD = "article_standard"
    RESEARCH_PACKAGE = "research_package"
    BUNDLE_ARTICLE_PRESENTATION = "bundle_article_presentation"
