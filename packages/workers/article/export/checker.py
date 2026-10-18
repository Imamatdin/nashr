"""Compliance checker: read a produced DOCX back and verify it rule by rule.

The checker never trusts the builder's intentions; it opens the bytes with
python-docx and asserts what Word would actually render. Each profile rule yields
one :class:`ComplianceCheck` with status ``pass``, ``fail`` or ``unknown``. A rule
whose value cannot be read back (an inherited-and-unset style attribute, a missing
abstract) is ``unknown`` and is never counted as a pass (D8, I-B6-6).

The result is stored with the export so B7 can show it without re-running the
check. We keep it in the export's metadata rather than a new table (recorded in
the lane file): it is small, immutable with its export, and never queried across
exports.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from docx import Document  # pyright: ignore[reportUnknownVariableType]
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import Language
from packages.workers.article.export.labels import ABSTRACT_HEADING
from packages.workers.article.export.models import ComplianceStatus
from packages.workers.article.export.profiles import (
    Alignment,
    ArticleProfile,
    HeadingStyle,
    RuleSource,
)

_CM_TOLERANCE = 0.03
_PT_TOLERANCE = 0.3
_SPACING_TOLERANCE = 0.01

_ALIGN_BACK: dict[WD_ALIGN_PARAGRAPH, Alignment] = {
    WD_ALIGN_PARAGRAPH.LEFT: "left",
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
}


class ComplianceCheck(BaseModel):
    """One rule's verdict. ``rule_key`` is the four-language message key."""

    model_config = ConfigDict(extra="forbid")

    rule_key: str = Field(min_length=1, max_length=64)
    status: ComplianceStatus
    expected: str = Field(max_length=200)
    actual: str = Field(max_length=200)
    source: RuleSource


class ComplianceReport(BaseModel):
    """Every rule's verdict for one produced DOCX against one profile."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1, max_length=64)
    profile_verified: bool
    checks: list[ComplianceCheck] = Field(default_factory=list[ComplianceCheck])

    @property
    def passed(self) -> int:
        return sum(1 for check in self.checks if check.status == "pass")

    @property
    def failed(self) -> int:
        return sum(1 for check in self.checks if check.status == "fail")

    @property
    def unknown(self) -> int:
        return sum(1 for check in self.checks if check.status == "unknown")

    @property
    def has_failures(self) -> bool:
        return self.failed > 0


def check_compliance(
    docx_bytes: bytes, profile: ArticleProfile, language: Language
) -> ComplianceReport:
    """Open the DOCX and return a verdict for every rule in ``profile``."""

    document: Any = Document(BytesIO(docx_bytes))
    checks: list[ComplianceCheck] = []
    checks.append(_check_page_size(document, profile))
    checks.extend(_check_margins(document, profile))
    checks.append(_check_body_font(document, profile))
    checks.append(_check_body_size(document, profile))
    checks.append(_check_line_spacing(document, profile))
    checks.append(_check_first_line_indent(document, profile))
    for heading in profile.headings:
        checks.append(_check_heading(document, profile, heading))
    checks.append(_check_page_numbers(document, profile))
    checks.append(_check_title_page(profile))
    if profile.abstract_min_words is not None and profile.abstract_max_words is not None:
        checks.append(_check_abstract(document, profile, language))
    return ComplianceReport(profile_id=profile.id, profile_verified=profile.verified, checks=checks)


# ---------------------------------------------------------------------------
# Individual rule checks
# ---------------------------------------------------------------------------


def _verdict(matches: bool) -> ComplianceStatus:
    return "pass" if matches else "fail"


def _near(a: float | None, b: float, tolerance: float) -> bool:
    return a is not None and abs(a - b) <= tolerance


def _check_page_size(document: Any, profile: ArticleProfile) -> ComplianceCheck:
    section = document.sections[0]
    width = _cm(section.page_width)
    height = _cm(section.page_height)
    expected = f"{profile.page_width_cm:.2f}x{profile.page_height_cm:.2f} cm"
    if width is None or height is None:
        return _check("page_size", "unknown", expected, "unreadable", profile)
    ok = _near(width, profile.page_width_cm, _CM_TOLERANCE) and _near(
        height, profile.page_height_cm, _CM_TOLERANCE
    )
    return _check("page_size", _verdict(ok), expected, f"{width:.2f}x{height:.2f} cm", profile)


def _check_margins(document: Any, profile: ArticleProfile) -> list[ComplianceCheck]:
    section = document.sections[0]
    top = _cm(section.top_margin)
    bottom = _cm(section.bottom_margin)
    left = _cm(section.left_margin)
    right = _cm(section.right_margin)
    expected = (
        f"T{profile.margin_top_cm} B{profile.margin_bottom_cm} "
        f"L{profile.margin_left_cm} R{profile.margin_right_cm} cm"
    )
    if None in (top, bottom, left, right):
        return [_check("margins", "unknown", expected, "unreadable", profile)]
    ok = (
        _near(top, profile.margin_top_cm, _CM_TOLERANCE)
        and _near(bottom, profile.margin_bottom_cm, _CM_TOLERANCE)
        and _near(left, profile.margin_left_cm, _CM_TOLERANCE)
        and _near(right, profile.margin_right_cm, _CM_TOLERANCE)
    )
    actual = f"T{top:.2f} B{bottom:.2f} L{left:.2f} R{right:.2f} cm"
    return [_check("margins", _verdict(ok), expected, actual, profile)]


def _check_body_font(document: Any, profile: ArticleProfile) -> ComplianceCheck:
    style = document.styles["Normal"]
    slots = _font_slots(style.element)
    expected = profile.body_font
    if not slots:
        return _check("body_font", "unknown", expected, "no font slots", profile)
    # I-B6-2: ascii, eastAsia and cs must all name the profile font so Cyrillic
    # and Latin share the face. A missing slot is a fail, not a pass.
    wanted = {"w:ascii", "w:eastAsia", "w:cs"}
    actual = ",".join(f"{slot.split(':')[1]}={slots.get(slot, '-')}" for slot in sorted(wanted))
    ok = all(slots.get(slot) == profile.body_font for slot in wanted)
    return _check("body_font", _verdict(ok), expected, actual[:200], profile)


def _check_body_size(document: Any, profile: ArticleProfile) -> ComplianceCheck:
    size = _pt(document.styles["Normal"].font.size)
    expected = f"{profile.body_size_pt} pt"
    if size is None:
        return _check("body_size", "unknown", expected, "unset", profile)
    ok = _near(size, profile.body_size_pt, _PT_TOLERANCE)
    return _check("body_size", _verdict(ok), expected, f"{size:.1f} pt", profile)


def _check_line_spacing(document: Any, profile: ArticleProfile) -> ComplianceCheck:
    spacing = document.styles["Normal"].paragraph_format.line_spacing
    expected = f"{profile.line_spacing}x"
    if not isinstance(spacing, float | int):
        return _check("line_spacing", "unknown", expected, "unset", profile)
    ok = _near(float(spacing), profile.line_spacing, _SPACING_TOLERANCE)
    return _check("line_spacing", _verdict(ok), expected, f"{float(spacing):.2f}x", profile)


def _check_first_line_indent(document: Any, profile: ArticleProfile) -> ComplianceCheck:
    indent = _cm(document.styles["Normal"].paragraph_format.first_line_indent)
    expected = f"{profile.first_line_indent_cm} cm"
    if indent is None:
        return _check("first_line_indent", "unknown", expected, "unset", profile)
    ok = _near(indent, profile.first_line_indent_cm, _CM_TOLERANCE)
    return _check("first_line_indent", _verdict(ok), expected, f"{indent:.2f} cm", profile)


def _check_heading(
    document: Any, profile: ArticleProfile, heading: HeadingStyle
) -> ComplianceCheck:
    rule_key = f"heading_{heading.level}"
    style = document.styles[f"Heading {heading.level}"]
    size = _pt(style.font.size)
    bold = style.font.bold
    italic = style.font.italic
    alignment = style.paragraph_format.alignment
    expected = (
        f"{heading.size_pt}pt bold={heading.bold} italic={heading.italic} {heading.alignment}"
    )
    if size is None or bold is None or italic is None or alignment is None:
        return _check(rule_key, "unknown", expected, "style attrs unset", profile)
    align_back = _ALIGN_BACK.get(alignment)
    ok = (
        _near(size, heading.size_pt, _PT_TOLERANCE)
        and bool(bold) == heading.bold
        and bool(italic) == heading.italic
        and align_back == heading.alignment
    )
    actual = f"{size:.1f}pt bold={bool(bold)} italic={bool(italic)} {align_back}"
    return _check(rule_key, _verdict(ok), expected, actual, profile)


def _check_page_numbers(document: Any, profile: ArticleProfile) -> ComplianceCheck:
    present = _has_page_field(document)
    if profile.page_numbers.enabled:
        expected = "PAGE field present"
        return _check("page_numbers", _verdict(present), expected, str(present), profile)
    expected = "no page numbers"
    return _check("page_numbers", _verdict(not present), expected, f"present={present}", profile)


def _check_title_page(profile: ArticleProfile) -> ComplianceCheck:
    # A title page cannot be verified structurally from the DOCX with confidence
    # (it is ordinary paragraphs before a page break), so this is honestly
    # reported as unknown rather than claimed as a pass (D8).
    return _check(
        "title_page", "unknown", profile.title_page.value, "not structurally verifiable", profile
    )


def _check_abstract(document: Any, profile: ArticleProfile, language: Language) -> ComplianceCheck:
    assert profile.abstract_min_words is not None and profile.abstract_max_words is not None
    expected = f"{profile.abstract_min_words}-{profile.abstract_max_words} words"
    heading_text = ABSTRACT_HEADING[language].strip().casefold()
    paragraphs = list(document.paragraphs)
    for index, paragraph in enumerate(paragraphs):
        if paragraph.text.strip().casefold() == heading_text:
            body = _next_nonempty(paragraphs, index + 1)
            if body is None:
                return _check(
                    "abstract_word_count", "unknown", expected, "no abstract text", profile
                )
            count = len(body.split())
            ok = profile.abstract_min_words <= count <= profile.abstract_max_words
            return _check("abstract_word_count", _verdict(ok), expected, f"{count} words", profile)
    return _check("abstract_word_count", "unknown", expected, "no abstract section", profile)


# ---------------------------------------------------------------------------
# Readback helpers
# ---------------------------------------------------------------------------


def _check(
    rule_key: str,
    status: ComplianceStatus,
    expected: str,
    actual: str,
    profile: ArticleProfile,
) -> ComplianceCheck:
    # Every rule key emitted here is also a profile source key (enforced by the
    # profile validator), so provenance is always available.
    return ComplianceCheck(
        rule_key=rule_key,
        status=status,
        expected=expected,
        actual=actual,
        source=profile.sources[rule_key],
    )


def _cm(length: Any) -> float | None:
    if length is None:
        return None
    try:
        return float(length.cm)
    except (AttributeError, TypeError):
        return None


def _pt(size: Any) -> float | None:
    if size is None:
        return None
    try:
        return float(size.pt)
    except (AttributeError, TypeError):
        return None


def _font_slots(style_element: Any) -> dict[str, str]:
    rpr = style_element.find(qn("w:rPr"))
    if rpr is None:
        return {}
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        return {}
    slots: dict[str, str] = {}
    for slot in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        value = rfonts.get(qn(slot))
        if value is not None:
            slots[slot] = str(value)
    return slots


def _has_page_field(document: Any) -> bool:
    for section in document.sections:
        footer = section.footer
        xml = footer._element.xml  # pyright: ignore[reportPrivateUsage]
        if "PAGE" in xml and "fldChar" in xml:
            return True
    return False


def _next_nonempty(paragraphs: list[Any], start: int) -> str | None:
    for paragraph in paragraphs[start:]:
        text = paragraph.text.strip()
        if text:
            return text
    return None


__all__ = ["ComplianceCheck", "ComplianceReport", "check_compliance"]
