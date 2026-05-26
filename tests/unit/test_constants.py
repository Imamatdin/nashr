"""Tests for ``packages.core.constants``: types, ranges, and disjointness."""

from __future__ import annotations

from packages.core import constants
from packages.core.enums import JobType


def test_size_limits_are_sane() -> None:
    assert constants.MAX_FILE_SIZE_BYTES == 20 * 1024 * 1024
    assert constants.MAX_STORAGE_PER_USER_BYTES == 200 * 1024 * 1024
    assert constants.MAX_STORAGE_PER_USER_BYTES > constants.MAX_FILE_SIZE_BYTES


def test_slide_count_bounds() -> None:
    assert constants.MIN_SLIDES == 3
    assert constants.MAX_SLIDES == 20
    assert constants.MIN_SLIDES < constants.MAX_SLIDES


def test_text_limits() -> None:
    assert constants.MAX_TITLE_LENGTH == 70
    assert constants.MAX_SUBTITLE_LENGTH == 130
    assert constants.MAX_BODY_ITEM_LENGTH == 120
    assert constants.MAX_BODY_ITEMS == 4


def test_font_size_minimums_are_positive_ints() -> None:
    assert isinstance(constants.MIN_FONT_SIZE_BODY, int)
    assert isinstance(constants.MIN_FONT_SIZE_TITLE, int)
    assert constants.MIN_FONT_SIZE_BODY >= 12
    assert constants.MIN_FONT_SIZE_TITLE > constants.MIN_FONT_SIZE_BODY


def test_credit_caps_keys() -> None:
    assert set(constants.CREDIT_CAPS) == {"daily", "weekly", "per_project"}
    assert all(isinstance(v, int) and v > 0 for v in constants.CREDIT_CAPS.values())
    assert constants.CREDIT_CAPS["daily"] <= constants.CREDIT_CAPS["weekly"]


def test_free_credit_expiry_is_quarter_year_or_more() -> None:
    assert constants.FREE_CREDIT_EXPIRY_DAYS >= 30


def test_job_cost_limits_cover_every_job_type() -> None:
    for job_type in JobType:
        assert job_type in constants.JOB_COST_LIMITS, (
            f"Missing JOB_COST_LIMITS entry for {job_type}"
        )
        assert constants.JOB_COST_LIMITS[job_type] > 0


def test_allowed_and_blocked_file_types_are_disjoint() -> None:
    intersection = constants.ALLOWED_FILE_TYPES & constants.BLOCKED_FILE_TYPES
    assert intersection == frozenset(), f"file-type sets overlap: {intersection!r}"


def test_allowed_file_types_includes_all_doc_formats() -> None:
    must_include = {"pdf", "docx", "pptx", "png", "jpeg", "txt"}
    assert must_include <= constants.ALLOWED_FILE_TYPES


def test_blocked_file_types_includes_executables_and_scripts() -> None:
    must_block = {"javascript", "executable", "shell", "python"}
    assert must_block <= constants.BLOCKED_FILE_TYPES


def test_magika_min_confidence_is_probability() -> None:
    assert 0.0 < constants.MAGIKA_MIN_CONFIDENCE <= 1.0


def test_pricing_tiers_are_monotone() -> None:
    p = constants.PRICING_UZS
    assert p["presentation_basic"] < p["presentation_standard"] < p["presentation_premium"]
    assert p["article_short"] < p["article_standard"] < p["research_package"]


def test_export_expiry_is_seven_days() -> None:
    assert constants.EXPORT_URL_EXPIRY_SECONDS == 7 * 24 * 60 * 60


def test_image_tier_limits_match_pricing() -> None:
    from packages.core.enums import GenerationPackage

    limits = constants.PRESENTATION_TIER_IMAGE_LIMITS
    assert limits[GenerationPackage.PRESENTATION_BASIC] == 0
    assert limits[GenerationPackage.PRESENTATION_STANDARD] >= 1
    assert (
        limits[GenerationPackage.PRESENTATION_PREMIUM]
        > limits[GenerationPackage.PRESENTATION_STANDARD]
    )


def test_image_tier_limits_cover_every_presentation_tier() -> None:
    """Invariant I1: every presentation GenerationPackage has a budget.

    Adding a new presentation_* tier without an entry here would silently
    fall through ``image_budget_for_package``'s fallback — exactly the
    class of bug the typed re-key was meant to prevent. This assertion
    fails the build until the new tier is added.
    """

    from packages.core.enums import GenerationPackage

    presentation_tiers = {p for p in GenerationPackage if p.value.startswith("presentation_")}
    assert presentation_tiers == set(constants.PRESENTATION_TIER_IMAGE_LIMITS.keys())


def test_image_budget_for_package_is_monotone_across_paid_tiers() -> None:
    """Invariant I1: tier difference must be observable in output.

    The function is the single seam between billing and the image engine; if
    PREMIUM does not strictly exceed STANDARD which does not exceed BASIC,
    every paid difference downstream is fictional.
    """

    from packages.core.enums import GenerationPackage

    basic = constants.image_budget_for_package(GenerationPackage.PRESENTATION_BASIC)
    standard = constants.image_budget_for_package(GenerationPackage.PRESENTATION_STANDARD)
    premium = constants.image_budget_for_package(GenerationPackage.PRESENTATION_PREMIUM)
    assert basic == 0
    assert standard > basic
    assert premium > standard


def test_image_budget_for_package_falls_back_on_non_presentation_tier() -> None:
    """Defensive: non-presentation packages (article, bundle) get the standard
    fallback so a not-yet-wired tier never silently ships a zero-image deck.
    See INVARIANTS.md authorized deferral for the bundle.
    """

    from packages.core.enums import GenerationPackage

    standard_budget = constants.image_budget_for_package(GenerationPackage.PRESENTATION_STANDARD)
    assert (
        constants.image_budget_for_package(GenerationPackage.BUNDLE_ARTICLE_PRESENTATION)
        == standard_budget
    )
    assert constants.image_budget_for_package(GenerationPackage.ARTICLE_SHORT) == standard_budget


def test_ocr_languages_includes_uzbek_russian_english() -> None:
    assert {"uzb", "rus", "eng"} <= set(constants.OCR_LANGUAGES)
