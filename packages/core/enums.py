"""Enums shared across all Nashr modules.

Every string-valued constant that participates in a database column or pydantic
field lives here. Values are stable wire-format identifiers and must not change
without a migration.
"""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    """User-facing language codes.

    Karakalpak (kaa) is distinct from Uzbek (uz) — different vocabulary
    for navigation chrome ("Kelesi"/"Artqa" vs "Keyingi"/"Orqaga"),
    different feedback labels, different orthographic conventions.
    """

    UZ = "uz"
    RU = "ru"
    EN = "en"
    KAA = "kaa"


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
    """Bibliography style supported by the article worker.

    GOST is the CIS academic standard (default for Uzbek and Russian
    output). APA is the default for English output. IEEE is offered for
    engineering/CS articles. Chicago and Vancouver are present because
    some Uzbek universities mandate footnote-based or numeric medical
    styles for specific faculties.
    """

    GOST = "gost"
    APA = "apa"
    IEEE = "ieee"
    CHICAGO = "chicago"
    VANCOUVER = "vancouver"


class SourceType(StrEnum):
    """Bibliographic kind of a single citable source.

    Drives format selection in :class:`BibliographyFormatter`: a journal
    article rendered in GOST uses ``//`` and an issue/volume block, a
    book uses ``— City: Publisher, Year. — N с.``, a web page adds the
    ``[Электронный ресурс]`` marker, and so on.
    """

    JOURNAL_ARTICLE = "journal_article"
    BOOK = "book"
    BOOK_CHAPTER = "book_chapter"
    CONFERENCE_PAPER = "conference_paper"
    DISSERTATION = "dissertation"
    WEB_PAGE = "web_page"
    REPORT = "report"
    LEGAL_DOCUMENT = "legal_document"
    DATASET = "dataset"
    OTHER = "other"


class ArticleSectionStatus(StrEnum):
    """Drafting state of one article section."""

    DRAFT = "draft"
    VERIFIED = "verified"
    REVISED = "revised"
    FINAL = "final"


class SlideType(StrEnum):
    """All 22 slide layout types defined by Design Language v2.

    Each value maps to a concrete layout specification in the renderer:
    region geometry, typography hierarchy, and content slot count.
    """

    TITLE_HERO = "title_hero"
    CONCEPT_DEFINITION = "concept_definition"
    GALLERY_PEOPLE = "gallery_people"
    TYPOGRAPHIC_KEYWORDS = "typographic_keywords"
    CONTENT_SPLIT = "content_split"
    DATA_EMPHASIS = "data_emphasis"
    COMPARISON = "comparison"
    TIMELINE = "timeline"
    FLOW_PROCESS = "flow_process"
    QUOTE_PULLQUOTE = "quote_pullquote"
    CHART_DATA = "chart_data"
    TABLE_COMPACT = "table_compact"
    SECTION_BREAK = "section_break"
    SUMMARY_TAKEAWAY = "summary_takeaway"
    RESOURCES_LINKS = "resources_links"
    TEAM_CREDITS = "team_credits"
    INTERACTIVE_QUIZ_MCQ = "interactive_quiz_mcq"
    INTERACTIVE_MATCHING = "interactive_matching"
    INTERACTIVE_CATEGORIZE = "interactive_categorize"
    INTERACTIVE_FILL_BLANK = "interactive_fill_blank"
    INTERACTIVE_TRUE_FALSE = "interactive_true_false"
    INTERACTIVE_DEBATE = "interactive_debate"


class PresentationMood(StrEnum):
    """Aesthetic mood that drives palette, typography, and decorative choices."""

    WARM_HISTORICAL = "warm_historical"
    BOLD_TECHNICAL = "bold_technical"
    CLEAN_PROFESSIONAL = "clean_professional"
    CALM_MEDICAL = "calm_medical"
    NATURAL = "natural"
    INSTITUTIONAL = "institutional"


class BackgroundTreatment(StrEnum):
    """Deck-level light/dark background polarity."""

    DARK = "dark"
    LIGHT = "light"


class ExportFormat(StrEnum):
    """Primary output formats the renderer can emit."""

    HTML = "html"
    PPTX_EDITABLE = "pptx_editable"
    PPTX_STUDIO = "pptx_studio"
    PDF = "pdf"


class TitleStyle(StrEnum):
    """Editorial style for slide titles.

    ``TOPIC`` produces short noun-phrase titles ("Methodology", "Results").
    ``TAKEAWAY`` produces action/finding titles ("94% water savings in Seattle").
    Design Language R08 defaults the engine to ``TAKEAWAY``.
    """

    TOPIC = "topic"
    TAKEAWAY = "takeaway"


class AudienceType(StrEnum):
    """Granular presentation audience for register and design routing."""

    SCHOOL = "school"
    UNDERGRADUATE = "undergraduate"
    GRADUATE = "graduate"
    ACADEMIC_CONFERENCE = "academic_conference"
    MIXED_ACADEMIC_INDUSTRY = "mixed_academic_industry"
    PROFESSIONAL = "professional"
    GENERAL_PUBLIC = "general_public"


class NarrativeEmphasis(StrEnum):
    """Which arc the deck should prioritise."""

    PROBLEM_FRAMING = "problem_framing"
    TECHNICAL_MECHANISM = "technical_mechanism"
    METHODOLOGY = "methodology"
    RESULTS_NUMBERS = "results_numbers"
    ROADMAP_SCALABILITY = "roadmap_scalability"
    BALANCED = "balanced"


class NarrativePhase(StrEnum):
    """One ordered phase in a deck's narrative arc.

    Phases are the high-level story beats that the Editorial Pass uses to
    place slides; every content slide belongs to exactly one phase, and the
    ``emphasis_phase`` chosen by the arc selector gets the largest share of
    the slide budget.
    """

    HOOK = "hook"
    CONTEXT = "context"
    CORE = "core"
    EVIDENCE = "evidence"
    IMPLICATIONS = "implications"
    CLOSE = "close"


class SpeakerNotesStyle(StrEnum):
    """How extensive speaker notes should be on each slide."""

    FULL_SCRIPT = "full_script"
    BRIEF_TALKING_POINTS = "brief_talking_points"
    NO_NOTES = "no_notes"


class DiagramStrategy(StrEnum):
    """How the engine should handle diagrams in technical content."""

    BUILD_SVG = "build_svg"
    PLACEHOLDER = "placeholder"
    MINIMAL_TEXT = "minimal_text"
    NONE = "none"


class AuditSeverity(StrEnum):
    """Severity tier for a single quality-audit finding."""

    FAIL = "fail"
    WARN = "warn"


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


class ClaimType(StrEnum):
    """Rhetorical category of a single source claim.

    Used by the article outline generator to route claims into the
    correct article section: statistical findings belong in Results,
    theoretical arguments in Literature Review, methodology
    descriptions in Methods, and so on.
    """

    EMPIRICAL_FINDING = "empirical_finding"
    STATISTICAL_RESULT = "statistical_result"
    THEORETICAL_ARGUMENT = "theoretical_argument"
    METHODOLOGICAL = "methodological"
    DEFINITION = "definition"
    RECOMMENDATION = "recommendation"
    COMPARISON = "comparison"
    LIMITATION = "limitation"
    GENERAL_FACT = "general_fact"


class CitationStatus(StrEnum):
    """State of a single evidence_matrix row."""

    READY = "ready"
    NEEDS_USER_INPUT = "needs_user_input"
    UNSUPPORTED = "unsupported"
    VERIFIED = "verified"


class CitationVerdict(StrEnum):
    """Verifier's judgement of how well a source supports a cited claim.

    Emitted by :class:`packages.workers.article.citation_verifier.CitationVerifier`
    for each citation in a drafted article. ``SOURCE_NOT_FOUND`` is a
    structural verdict assigned without an LLM call when the cited
    ``source_chunk_id`` or ``claim_id`` is not present in the project's
    extracted material.
    """

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    OVERCLAIMED = "overclaimed"
    NOT_SUPPORTED = "not_supported"
    CONTRADICTED = "contradicted"
    SOURCE_NOT_FOUND = "source_not_found"


class ResearchQuestionType(StrEnum):
    """Categories of question posed during the research interview."""

    THESIS_CLARITY = "thesis_clarity"
    SOURCE_COVERAGE = "source_coverage"
    ORIGINALITY = "originality"
    CONTRADICTION = "contradiction"


class InterviewMode(StrEnum):
    """Depth of the research interview chosen by the user.

    ``FAST`` is the no-interview path and never reaches the engine; the
    engine itself only handles ``GUIDED`` and ``RESEARCH``.
    """

    FAST = "fast"
    GUIDED = "guided"
    RESEARCH = "research"


class WeaknessDimension(StrEnum):
    """Axes along which the evidence matrix can be weak."""

    THESIS_CLARITY = "thesis_clarity"
    SOURCE_COVERAGE = "source_coverage"
    CONTRADICTION_AWARENESS = "contradiction_awareness"
    ORIGINALITY = "originality"
    EVIDENCE_DEPTH = "evidence_depth"


class CreditCapHit(StrEnum):
    """Which cap blocked a credit award, when one did."""

    DAILY = "daily"
    WEEKLY = "weekly"
    PER_PROJECT = "per_project"


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


class CalibrationLevel(StrEnum):
    """Academic register the article drafter should write at.

    The level adapts vocabulary, sentence complexity, and analytical
    sophistication to the user's demonstrated capability — not to make
    output worse for younger users, but to match the register a real
    writer at that level would actually produce.
    """

    SCHOOL = "school"
    UNDERGRADUATE = "undergraduate"
    MASTERS = "masters"
    DOCTORAL = "doctoral"
    PROFESSIONAL = "professional"


class GenerationPackage(StrEnum):
    """Pricing tiers offered to the user."""

    PRESENTATION_BASIC = "presentation_basic"
    PRESENTATION_STANDARD = "presentation_standard"
    PRESENTATION_PREMIUM = "presentation_premium"
    ARTICLE_SHORT = "article_short"
    ARTICLE_STANDARD = "article_standard"
    RESEARCH_PACKAGE = "research_package"
    BUNDLE_ARTICLE_PRESENTATION = "bundle_article_presentation"
