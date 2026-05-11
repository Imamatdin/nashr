"""Pre-generation interview engine for the presentation pipeline.

The engine has three jobs:

1. :meth:`PresentationInterviewEngine.generate_questions` — analyse source
   material, detect the academic domain, count available stats/people,
   and return a localised question list. No LLM call: the questions are
   defined in code and parameterised by content analysis.
2. :meth:`PresentationInterviewEngine.apply_answers` — fold raw user
   answers into a typed :class:`PresentationInterviewAnswers`, resolving
   any "decide_for_me" answers via the same defaulting logic used when
   the interview is skipped entirely.
3. :meth:`PresentationInterviewEngine.apply_defaults` — produce an
   answers object straight from content analysis, used by the "just make
   me a deck" path that skips the interview.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from packages.core.enums import (
    AudienceType,
    BackgroundTreatment,
    DiagramStrategy,
    Language,
    NarrativeEmphasis,
    PresentationMood,
    SpeakerNotesStyle,
    TitleStyle,
)
from packages.core.models.article import ArticleOutline
from packages.core.models.presentation import (
    InterviewQuestion,
    InterviewQuestionOption,
    PresentationInterviewAnswers,
    PresentationInterviewQuestions,
)
from packages.core.models.source import (
    SourceChunkCreate,
    SourceClaimCreate,
    SourceMetadataExtracted,
)
from packages.core.models.suggestion import AcademicDomain
from packages.presentation._labels import (
    AUDIENCE_OPTIONS,
    DIAGRAM_OPTIONS,
    EMPHASIS_OPTIONS,
    HELP_TEXT,
    INTERACTIVE_OPTIONS,
    PLACEHOLDER_TEXT,
    QUESTION_TEXT,
    SPEAKER_NOTES_OPTIONS,
    THEME_OPTIONS,
    TITLE_STYLE_OPTIONS,
    OptionSpec,
)
from packages.suggestions.domain_detector import DomainDetector

_TECHNICAL_DOMAINS: frozenset[AcademicDomain] = frozenset(
    {AcademicDomain.ENGINEERING, AcademicDomain.COMPUTER_SCIENCE, AcademicDomain.MEDICAL}
)

_INTERACTIVE_DEFAULT_DOMAINS: frozenset[AcademicDomain] = frozenset(
    {AcademicDomain.EDUCATION, AcademicDomain.SOCIAL_SCIENCES, AcademicDomain.GENERAL}
)

_DOMAIN_TO_MOOD: dict[AcademicDomain, PresentationMood] = {
    AcademicDomain.MEDICAL: PresentationMood.CALM_MEDICAL,
    AcademicDomain.ENGINEERING: PresentationMood.BOLD_TECHNICAL,
    AcademicDomain.COMPUTER_SCIENCE: PresentationMood.BOLD_TECHNICAL,
    AcademicDomain.ECONOMICS: PresentationMood.CLEAN_PROFESSIONAL,
    AcademicDomain.LEGAL: PresentationMood.INSTITUTIONAL,
    AcademicDomain.ENVIRONMENTAL: PresentationMood.NATURAL,
    AcademicDomain.EDUCATION: PresentationMood.WARM_HISTORICAL,
    AcademicDomain.AGRICULTURE: PresentationMood.NATURAL,
    AcademicDomain.SOCIAL_SCIENCES: PresentationMood.CLEAN_PROFESSIONAL,
    AcademicDomain.GENERAL: PresentationMood.CLEAN_PROFESSIONAL,
}

_DECIDE_FOR_ME: str = "decide_for_me"

# Curated list of full and short names commonly used as people identifiers in
# claim text. Enough to power the "people available" heuristic without paying
# for a NER service.
_PERSON_KEYWORDS: frozenset[str] = frozenset(
    {
        "newton",
        "leibniz",
        "euler",
        "darwin",
        "einstein",
        "tesla",
        "edison",
        "curie",
        "voltaire",
        "monteske",
        "montesquieu",
        "rousseau",
        "kant",
        "hegel",
        "marx",
        "smith",
        "keynes",
        "fisher",
        "pasteur",
        "koch",
        "fleming",
        "freud",
        "jung",
        "skinner",
        "piaget",
        "vygotsky",
        "navoiy",
        "beruniy",
        "ibn sino",
        "ulug'bek",
        "al-xorazmiy",
        "ал-хорезми",
        "ибн сина",
        "беруни",
        "тимуридов",
    }
)


def _resolve_language(language: str | Language) -> Language:
    if isinstance(language, Language):
        return language
    normalised = language.strip().lower()
    for member in Language:
        if member.value == normalised:
            return member
    return Language.UZ


class PresentationInterviewEngine:
    """Builds the pre-generation interview questions and resolves the answers."""

    def __init__(self) -> None:
        self._domain_detector = DomainDetector()

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def generate_questions(
        self,
        claims: list[SourceClaimCreate],
        chunks: list[SourceChunkCreate],
        source_metadata: list[SourceMetadataExtracted],
        outline: ArticleOutline | None = None,
        language: str | Language = Language.UZ,
    ) -> PresentationInterviewQuestions:
        """Return the localised interview questions for the given content."""

        lang = _resolve_language(language)
        detection = self._domain_detector.detect_domains(
            claims=claims, chunks=chunks, outline=outline, source_metadata=source_metadata
        )
        domain = detection.primary_domain
        stat_count = _count_stat_claims(claims)
        people_count = _count_people(claims, chunks)
        estimated_slides = _estimate_slide_count(len(claims))

        questions: list[InterviewQuestion] = [
            _select_question("audience", AUDIENCE_OPTIONS, lang),
            _slider_question("duration", lang, min_value=5, max_value=45, default_value=15),
            _select_question("emphasis", EMPHASIS_OPTIONS, lang, question_type="multi_select"),
            _select_question("title_style", TITLE_STYLE_OPTIONS, lang),
            _select_question("include_interactive", INTERACTIVE_OPTIONS, lang),
            _select_question("theme", THEME_OPTIONS, lang),
            _select_question("speaker_notes", SPEAKER_NOTES_OPTIONS, lang),
        ]

        if stat_count > 0:
            questions.append(_text_question("headline_numbers", lang))

        questions.append(_text_question("closing_ask", lang))

        if domain in _TECHNICAL_DOMAINS:
            questions.append(_select_question("diagrams", DIAGRAM_OPTIONS, lang))

        return PresentationInterviewQuestions(
            questions=questions,
            detected_domain=domain.value,
            estimated_slide_count=estimated_slides,
            available_stats_count=stat_count,
            available_people_count=people_count,
        )

    def apply_answers(
        self,
        questions: PresentationInterviewQuestions,
        answers: Mapping[str, str | int | bool | list[str]],
    ) -> PresentationInterviewAnswers:
        """Fold a dictionary of raw user answers into structured preferences."""

        domain = _domain_from_string(questions.detected_domain)
        stat_count = questions.available_stats_count
        people_count = questions.available_people_count
        # The claim count isn't passed back through; derive it from the
        # estimated slide count so duration defaulting stays stable.
        approx_claims = _claims_from_estimated_slides(questions.estimated_slide_count)
        defaults = self._resolve_defaults(
            detected_domain=domain,
            claim_count=approx_claims,
            stat_count=stat_count,
            people_count=people_count,
        )

        audience = _resolve_audience(answers.get("audience"), defaults.audience)
        duration = _resolve_duration(answers.get("duration"), defaults.talk_duration_minutes)
        emphasis = _resolve_emphasis(answers.get("emphasis"), defaults.narrative_emphasis)
        title_style = _resolve_title_style(answers.get("title_style"), defaults.title_style)
        include_interactive = _resolve_interactive(
            answers.get("include_interactive"), defaults.include_interactive
        )
        background = _resolve_theme(answers.get("theme"), defaults.background_treatment)
        speaker_notes = _resolve_speaker_notes(
            answers.get("speaker_notes"), defaults.speaker_notes_style
        )
        diagrams = _resolve_diagrams(answers.get("diagrams"), defaults.diagram_strategy)

        headline_numbers = _parse_headline_numbers(answers.get("headline_numbers"))
        closing_ask = _resolve_text(answers.get("closing_ask"))

        return PresentationInterviewAnswers(
            audience=audience,
            talk_duration_minutes=duration,
            language=defaults.language,
            narrative_emphasis=emphasis,
            title_style=title_style,
            include_interactive=include_interactive,
            mood_override=defaults.mood_override,
            background_treatment=background,
            diagram_strategy=diagrams,
            speaker_notes_style=speaker_notes,
            closing_ask=closing_ask,
            headline_numbers=headline_numbers,
            anchor_source_id=None,
        )

    def apply_defaults(
        self,
        claims: list[SourceClaimCreate],
        source_metadata: list[SourceMetadataExtracted],
        chunks: list[SourceChunkCreate] | None = None,
        outline: ArticleOutline | None = None,
        language: str | Language = Language.UZ,
    ) -> PresentationInterviewAnswers:
        """Skip the interview entirely and return content-derived defaults.

        ``language`` lets the caller pin the deck to a specific
        :class:`Language`. The default stays Uzbek so existing callers
        that pre-date Karakalpak support are unaffected.
        """

        chunks_in = chunks or []
        detection = self._domain_detector.detect_domains(
            claims=claims, chunks=chunks_in, outline=outline, source_metadata=source_metadata
        )
        stat_count = _count_stat_claims(claims)
        people_count = _count_people(claims, chunks_in)
        return self._resolve_defaults(
            detected_domain=detection.primary_domain,
            claim_count=len(claims),
            stat_count=stat_count,
            people_count=people_count,
            language=_resolve_language(language),
        )

    # ------------------------------------------------------------------
    # default resolution
    # ------------------------------------------------------------------

    def _resolve_defaults(
        self,
        detected_domain: AcademicDomain,
        claim_count: int,
        stat_count: int,
        people_count: int,
        language: Language = Language.UZ,
    ) -> PresentationInterviewAnswers:
        del stat_count, people_count  # reserved for future heuristics

        if claim_count < 30:
            duration = 15
        elif claim_count < 60:
            duration = 25
        else:
            duration = 35

        include_interactive = detected_domain in _INTERACTIVE_DEFAULT_DOMAINS
        mood = _DOMAIN_TO_MOOD.get(detected_domain, PresentationMood.CLEAN_PROFESSIONAL)
        background = (
            BackgroundTreatment.DARK
            if mood is PresentationMood.BOLD_TECHNICAL
            else BackgroundTreatment.LIGHT
        )

        return PresentationInterviewAnswers(
            audience=AudienceType.UNDERGRADUATE,
            talk_duration_minutes=duration,
            language=language,
            narrative_emphasis=NarrativeEmphasis.BALANCED,
            title_style=TitleStyle.TAKEAWAY,
            include_interactive=include_interactive,
            mood_override=mood,
            background_treatment=background,
            diagram_strategy=DiagramStrategy.BUILD_SVG,
            speaker_notes_style=SpeakerNotesStyle.BRIEF_TALKING_POINTS,
            closing_ask=None,
            headline_numbers=[],
            anchor_source_id=None,
        )


# ---------------------------------------------------------------------------
# question construction helpers
# ---------------------------------------------------------------------------


def _select_question(
    question_id: str,
    options: list[OptionSpec],
    language: Language,
    question_type: str = "single_select",
) -> InterviewQuestion:
    return InterviewQuestion(
        question_id=question_id,
        question_text=QUESTION_TEXT[question_id][language.value],
        question_type=question_type,
        options=[
            InterviewQuestionOption(
                value=opt["value"],
                label=opt["label"][language.value],
                is_default=opt["is_default"],
            )
            for opt in options
        ],
    )


def _slider_question(
    question_id: str,
    language: Language,
    *,
    min_value: int,
    max_value: int,
    default_value: int,
) -> InterviewQuestion:
    return InterviewQuestion(
        question_id=question_id,
        question_text=QUESTION_TEXT[question_id][language.value],
        question_type="slider",
        min_value=min_value,
        max_value=max_value,
        default_value=default_value,
        help_text=HELP_TEXT[question_id][language.value],
    )


def _text_question(question_id: str, language: Language) -> InterviewQuestion:
    return InterviewQuestion(
        question_id=question_id,
        question_text=QUESTION_TEXT[question_id][language.value],
        question_type="text_input",
        placeholder=PLACEHOLDER_TEXT[question_id][language.value],
        help_text=HELP_TEXT[question_id][language.value],
    )


# ---------------------------------------------------------------------------
# content analysis helpers
# ---------------------------------------------------------------------------


def _count_stat_claims(claims: list[SourceClaimCreate]) -> int:
    from packages.core.enums import ClaimType

    return sum(1 for c in claims if c.claim_type is ClaimType.STATISTICAL_RESULT)


def _count_people(claims: list[SourceClaimCreate], chunks: list[SourceChunkCreate]) -> int:
    blob_parts: list[str] = []
    for claim in claims:
        blob_parts.append(claim.claim_text)
        if claim.quote:
            blob_parts.append(claim.quote)
    for chunk in chunks:
        blob_parts.append(chunk.text)
    blob = " ".join(blob_parts).lower()
    return sum(1 for kw in _PERSON_KEYWORDS if kw in blob)


def _estimate_slide_count(claim_count: int) -> int:
    if claim_count <= 0:
        return 8
    estimated = max(6, min(40, 6 + claim_count // 3))
    return estimated


def _claims_from_estimated_slides(estimated_slides: int) -> int:
    return max(0, (estimated_slides - 6) * 3)


# ---------------------------------------------------------------------------
# answer resolution helpers
# ---------------------------------------------------------------------------


def _str_value(raw: object) -> str | None:
    if isinstance(raw, str):
        return raw.strip() or None
    return None


def _iter_str_items(raw: object) -> list[str]:
    """Return the string members of an arbitrary value when it is a list."""
    if not isinstance(raw, list):
        return []
    items: list[str] = []
    for item in raw:  # type: ignore[reportUnknownVariableType]
        if isinstance(item, str):
            items.append(item)
    return items


def _domain_from_string(value: str) -> AcademicDomain:
    for member in AcademicDomain:
        if member.value == value:
            return member
    return AcademicDomain.GENERAL


def _resolve_audience(raw: object, fallback: AudienceType) -> AudienceType:
    value = _str_value(raw)
    if value and value != _DECIDE_FOR_ME:
        for member in AudienceType:
            if member.value == value:
                return member
    return fallback


def _resolve_duration(raw: object, fallback: int) -> int:
    if isinstance(raw, bool):
        return fallback
    if isinstance(raw, int) and 3 <= raw <= 60:
        return raw
    if isinstance(raw, str):
        try:
            value = int(raw)
            if 3 <= value <= 60:
                return value
        except ValueError:
            pass
    return fallback


def _resolve_emphasis(raw: object, fallback: NarrativeEmphasis) -> NarrativeEmphasis:
    list_items = _iter_str_items(raw)
    if list_items:
        picks = [item.strip() for item in list_items if item.strip()]
        picks = [p for p in picks if p != _DECIDE_FOR_ME]
        if len(picks) == 1:
            for member in NarrativeEmphasis:
                if member.value == picks[0]:
                    return member
        if len(picks) > 1:
            return NarrativeEmphasis.BALANCED
        return fallback
    if isinstance(raw, list):
        return fallback
    value = _str_value(raw)
    if value and value != _DECIDE_FOR_ME:
        for member in NarrativeEmphasis:
            if member.value == value:
                return member
    return fallback


def _resolve_title_style(raw: object, fallback: TitleStyle) -> TitleStyle:
    value = _str_value(raw)
    if value and value != _DECIDE_FOR_ME:
        for member in TitleStyle:
            if member.value == value:
                return member
    return fallback


def _resolve_interactive(raw: object, fallback: bool) -> bool:
    if isinstance(raw, bool):
        return raw
    value = _str_value(raw)
    if value == "yes":
        return True
    if value == "no":
        return False
    return fallback


def _resolve_theme(raw: object, fallback: BackgroundTreatment | None) -> BackgroundTreatment:
    value = _str_value(raw)
    if value == "light":
        return BackgroundTreatment.LIGHT
    if value == "dark":
        return BackgroundTreatment.DARK
    return fallback if fallback is not None else BackgroundTreatment.LIGHT


def _resolve_speaker_notes(raw: object, fallback: SpeakerNotesStyle) -> SpeakerNotesStyle:
    value = _str_value(raw)
    if value and value != _DECIDE_FOR_ME:
        for member in SpeakerNotesStyle:
            if member.value == value:
                return member
    return fallback


def _resolve_diagrams(raw: object, fallback: DiagramStrategy) -> DiagramStrategy:
    value = _str_value(raw)
    if value and value != _DECIDE_FOR_ME:
        for member in DiagramStrategy:
            if member.value == value:
                return member
    return fallback


def _resolve_text(raw: object) -> str | None:
    value = _str_value(raw)
    if value is None:
        return None
    return value[:500]


def _parse_headline_numbers(raw: object) -> list[str]:
    list_items = _iter_str_items(raw)
    if list_items:
        cleaned = [item.strip() for item in list_items if item.strip()]
        return cleaned[:10]
    if isinstance(raw, list):
        return []
    if isinstance(raw, str):
        # Split on commas, semicolons, or vertical bars; collapse whitespace.
        parts = re.split(r"[,;|]+", raw)
        cleaned = [re.sub(r"\s+", " ", p.strip()) for p in parts if p.strip()]
        return cleaned[:10]
    return []
