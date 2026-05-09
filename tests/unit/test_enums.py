"""Tests for the canonical enum set in ``packages.core.enums``.

These guard against accidental rename or duplicate value, which would silently
break wire-format compatibility with the database.
"""

from __future__ import annotations

from enum import Enum

import pytest

from packages.core import enums


def _all_enum_classes() -> list[type[Enum]]:
    return [
        obj
        for obj in vars(enums).values()
        if isinstance(obj, type) and issubclass(obj, Enum) and obj is not Enum
    ]


def test_no_enum_has_duplicate_values() -> None:
    for enum_cls in _all_enum_classes():
        values = [member.value for member in enum_cls]
        assert len(values) == len(set(values)), (
            f"{enum_cls.__name__} has duplicate values: {values}"
        )


@pytest.mark.parametrize(
    ("enum_cls", "expected"),
    [
        (enums.Language, {"uz", "ru", "en"}),
        (enums.Audience, {"talaba", "oqituvchi", "akademik", "biznes"}),
        (enums.ProjectType, {"presentation", "article", "research_package"}),
        (
            enums.ArticleStructure,
            {"referat", "kurs_ishi", "ilmiy_maqola", "hisobot"},
        ),
        (enums.CitationFormat, {"gost", "apa", "ieee"}),
        (
            enums.JobType,
            {
                "source_processing",
                "article_generation",
                "presentation_generation",
                "export",
            },
        ),
        (enums.JobStatus, {"queued", "processing", "completed", "failed"}),
        (
            enums.CreditReason,
            {
                "payment",
                "presentation_generation",
                "article_generation",
                "learning_reward",
                "refund",
            },
        ),
        (enums.OrderStatus, {"pending", "paid", "failed", "refunded"}),
        (enums.SourceQuality, {"strong", "medium", "weak", "invalid"}),
        (enums.ClaimStrength, {"strong", "moderate", "weak"}),
        (
            enums.CitationStatus,
            {"ready", "needs_user_input", "unsupported", "verified"},
        ),
    ],
)
def test_enum_membership(enum_cls: type[Enum], expected: set[str]) -> None:
    actual = {member.value for member in enum_cls}
    assert actual == expected, f"{enum_cls.__name__} differs from spec"


def test_slide_type_includes_all_quiz_kinds() -> None:
    quiz_members = {m.value for m in enums.SlideType if m.value.startswith("quiz_")}
    assert quiz_members == {
        "quiz_mcq",
        "quiz_matching",
        "quiz_categorize",
        "quiz_fill_blank",
        "quiz_true_false",
    }


def test_layout_mode_excludes_unrelated_values() -> None:
    values = {m.value for m in enums.LayoutMode}
    assert "title" not in values
    assert "split_left" in values and "split_right" in values
    assert "grid_cards" in values


def test_payment_provider_only_payme_and_click() -> None:
    assert {m.value for m in enums.PaymentProvider} == {"payme", "click"}


def test_str_enums_serialize_as_their_value() -> None:
    assert enums.Language.UZ.value == "uz"
    assert enums.JobStatus.COMPLETED.value == "completed"
