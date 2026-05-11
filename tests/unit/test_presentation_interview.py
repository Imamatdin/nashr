"""Behaviour tests for :class:`PresentationInterviewEngine`.

The engine is pure Python: no LLM call, no network I/O. Tests build small
claim/chunk fixtures, run the engine, and assert on the structured output.
"""

from __future__ import annotations

from packages.core.enums import (
    AudienceType,
    BackgroundTreatment,
    ClaimStrength,
    ClaimType,
    DiagramStrategy,
    NarrativeEmphasis,
    PresentationMood,
    SpeakerNotesStyle,
    TitleStyle,
)
from packages.core.models.presentation import (
    PresentationInterviewAnswers,
    PresentationInterviewQuestions,
)
from packages.core.models.source import SourceClaimCreate
from packages.core.models.suggestion import AcademicDomain
from packages.presentation.interview import PresentationInterviewEngine

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _claim(
    text: str,
    *,
    claim_type: ClaimType = ClaimType.GENERAL_FACT,
    strength: ClaimStrength = ClaimStrength.MODERATE,
) -> SourceClaimCreate:
    return SourceClaimCreate(claim_text=text, strength=strength, claim_type=claim_type)


def _medical_claims(n: int = 8) -> list[SourceClaimCreate]:
    base = [
        "Clinical trials show that patient diagnosis improves with biomarker screening.",
        "Treatment outcomes vary with therapy adherence in chronic disease cohorts.",
        "Hospital readmission rates dropped after pharmaceutical review protocols.",
        "The randomized placebo cohort study found significant mortality reduction.",
        "Vaccine efficacy depends on antibiotic stewardship and infection control.",
        "Pathology and oncology metrics correlate with morbidity outcomes.",
        "Mental health treatment for depression has reduced acute episodes.",
        "Surgery complication rates fell in the patient cohort under new protocols.",
    ]
    return [_claim(base[i % len(base)]) for i in range(n)]


def _engineering_claims(n: int = 8) -> list[SourceClaimCreate]:
    base = [
        "Finite element simulation of structural stress identified thermal failure modes.",
        "Sensor and actuator integration in the control system improved robotics yield.",
        "Optimization of the circuit signal reduced electrical loss across the system.",
        "Prototype manufacture used CAD to validate the design and material choice.",
        "The computational model simulated load across the structure under stress.",
        "Automation of the manufacture line cut prototype iteration time.",
        "Finite element analysis showed structural stress at the load boundary.",
        "Thermal simulation validated the design of the circuit under signal load.",
    ]
    return [_claim(base[i % len(base)]) for i in range(n)]


def _education_claims(n: int = 8) -> list[SourceClaimCreate]:
    base = [
        "Curriculum redesign improved student literacy and classroom learning outcomes.",
        "Pedagogy research links teacher feedback to higher assessment performance.",
        "Education policy raised university enrollment and reduced dropout rates.",
        "Literacy assessment in the classroom showed gains under new pedagogy.",
        "Student learning outcomes rose after curriculum and teacher training.",
        "Academic enrollment grew when school policy targeted dropout prevention.",
        "Teacher pedagogy training improved classroom assessment in literacy programs.",
        "Curriculum standards in education raised student literacy school-wide.",
    ]
    return [_claim(base[i % len(base)]) for i in range(n)]


def _stat_claims(n: int) -> list[SourceClaimCreate]:
    return [
        _claim(
            f"The system achieved {90 + i}.{i}% efficiency in measurement {i}.",
            claim_type=ClaimType.STATISTICAL_RESULT,
            strength=ClaimStrength.STRONG,
        )
        for i in range(n)
    ]


def _people_claims() -> list[SourceClaimCreate]:
    return [
        _claim("Newton's laws of motion underpin classical mechanics across the curriculum."),
        _claim("Leibniz independently developed calculus and proposed notation still in use."),
        _claim("Euler's identity unified analysis and is taught in modern mathematics."),
    ]


# ---------------------------------------------------------------------------
# generate_questions
# ---------------------------------------------------------------------------


def test_generate_questions_returns_at_least_seven_questions() -> None:
    engine = PresentationInterviewEngine()
    result = engine.generate_questions(
        claims=_education_claims(),
        chunks=[],
        source_metadata=[],
    )
    assert isinstance(result, PresentationInterviewQuestions)
    assert len(result.questions) >= 7


def test_generate_questions_detects_medical_domain() -> None:
    engine = PresentationInterviewEngine()
    result = engine.generate_questions(
        claims=_medical_claims(),
        chunks=[],
        source_metadata=[],
    )
    assert result.detected_domain == AcademicDomain.MEDICAL.value


def test_generate_questions_detects_engineering_domain() -> None:
    engine = PresentationInterviewEngine()
    result = engine.generate_questions(
        claims=_engineering_claims(),
        chunks=[],
        source_metadata=[],
    )
    assert result.detected_domain == AcademicDomain.ENGINEERING.value


def test_generate_questions_counts_stats() -> None:
    engine = PresentationInterviewEngine()
    claims = _education_claims() + _stat_claims(5)
    result = engine.generate_questions(claims=claims, chunks=[], source_metadata=[])
    assert result.available_stats_count == 5


def test_generate_questions_counts_people() -> None:
    engine = PresentationInterviewEngine()
    claims = _education_claims() + _people_claims()
    result = engine.generate_questions(claims=claims, chunks=[], source_metadata=[])
    assert result.available_people_count == 3


def test_generate_questions_includes_headline_numbers_only_when_stats_exist() -> None:
    engine = PresentationInterviewEngine()
    with_stats = engine.generate_questions(
        claims=_education_claims() + _stat_claims(3),
        chunks=[],
        source_metadata=[],
    )
    without_stats = engine.generate_questions(
        claims=_education_claims(),
        chunks=[],
        source_metadata=[],
    )
    with_stats_ids = {q.question_id for q in with_stats.questions}
    without_stats_ids = {q.question_id for q in without_stats.questions}
    assert "headline_numbers" in with_stats_ids
    assert "headline_numbers" not in without_stats_ids


def test_generate_questions_always_includes_closing_ask() -> None:
    engine = PresentationInterviewEngine()
    result = engine.generate_questions(
        claims=_education_claims(),
        chunks=[],
        source_metadata=[],
    )
    audience_q = next(q for q in result.questions if q.question_id == "audience")
    assert audience_q.options is not None
    audience_values = {opt.value for opt in audience_q.options}
    assert "academic_conference" in audience_values
    assert "closing_ask" in {q.question_id for q in result.questions}


def test_generate_questions_includes_diagrams_only_for_technical_domain() -> None:
    engine = PresentationInterviewEngine()
    engineering = engine.generate_questions(
        claims=_engineering_claims(), chunks=[], source_metadata=[]
    )
    education = engine.generate_questions(claims=_education_claims(), chunks=[], source_metadata=[])
    assert "diagrams" in {q.question_id for q in engineering.questions}
    assert "diagrams" not in {q.question_id for q in education.questions}


def test_generate_questions_trilingual_text() -> None:
    engine = PresentationInterviewEngine()
    claims = _education_claims()
    uz = engine.generate_questions(claims=claims, chunks=[], source_metadata=[], language="uz")
    ru = engine.generate_questions(claims=claims, chunks=[], source_metadata=[], language="ru")
    en = engine.generate_questions(claims=claims, chunks=[], source_metadata=[], language="en")
    audience_uz = next(q for q in uz.questions if q.question_id == "audience").question_text
    audience_ru = next(q for q in ru.questions if q.question_id == "audience").question_text
    audience_en = next(q for q in en.questions if q.question_id == "audience").question_text
    assert audience_uz == "Kim uchun tayyorlanmoqda?"
    assert audience_ru == "Для кого готовится?"
    assert audience_en == "Who is the audience?"


# ---------------------------------------------------------------------------
# apply_defaults
# ---------------------------------------------------------------------------


def test_apply_defaults_medical_domain() -> None:
    engine = PresentationInterviewEngine()
    defaults = engine.apply_defaults(claims=_medical_claims(), source_metadata=[])
    assert defaults.mood_override is PresentationMood.CALM_MEDICAL
    assert defaults.include_interactive is False
    assert defaults.background_treatment is BackgroundTreatment.LIGHT


def test_apply_defaults_engineering_domain() -> None:
    engine = PresentationInterviewEngine()
    defaults = engine.apply_defaults(claims=_engineering_claims(), source_metadata=[])
    assert defaults.mood_override is PresentationMood.BOLD_TECHNICAL
    assert defaults.background_treatment is BackgroundTreatment.DARK


def test_apply_defaults_education_domain() -> None:
    engine = PresentationInterviewEngine()
    defaults = engine.apply_defaults(claims=_education_claims(), source_metadata=[])
    assert defaults.mood_override is PresentationMood.WARM_HISTORICAL
    assert defaults.include_interactive is True


def test_apply_defaults_few_claims_short_duration() -> None:
    engine = PresentationInterviewEngine()
    defaults = engine.apply_defaults(claims=_education_claims(10), source_metadata=[])
    assert defaults.talk_duration_minutes == 15


def test_apply_defaults_many_claims_long_duration() -> None:
    engine = PresentationInterviewEngine()
    defaults = engine.apply_defaults(claims=_education_claims(80), source_metadata=[])
    assert defaults.talk_duration_minutes == 35


def test_apply_defaults_title_style_always_takeaway() -> None:
    engine = PresentationInterviewEngine()
    for claims in (_medical_claims(), _engineering_claims(), _education_claims()):
        defaults = engine.apply_defaults(claims=claims, source_metadata=[])
        assert defaults.title_style is TitleStyle.TAKEAWAY


# ---------------------------------------------------------------------------
# apply_answers
# ---------------------------------------------------------------------------


def test_apply_answers_direct_values() -> None:
    engine = PresentationInterviewEngine()
    questions = engine.generate_questions(claims=_education_claims(), chunks=[], source_metadata=[])
    answers: dict[str, str | int | bool | list[str]] = {
        "audience": "school",
        "duration": 10,
        "emphasis": ["methodology"],
        "title_style": "topic",
        "include_interactive": "yes",
        "theme": "dark",
        "speaker_notes": "full_script",
    }
    resolved = engine.apply_answers(questions, answers)
    assert resolved.audience is AudienceType.SCHOOL
    assert resolved.talk_duration_minutes == 10
    assert resolved.narrative_emphasis is NarrativeEmphasis.METHODOLOGY
    assert resolved.title_style is TitleStyle.TOPIC
    assert resolved.include_interactive is True
    assert resolved.background_treatment is BackgroundTreatment.DARK
    assert resolved.speaker_notes_style is SpeakerNotesStyle.FULL_SCRIPT


def test_apply_answers_decide_for_me_resolves_to_defaults() -> None:
    engine = PresentationInterviewEngine()
    questions = engine.generate_questions(
        claims=_engineering_claims(), chunks=[], source_metadata=[]
    )
    answers: dict[str, str | int | bool | list[str]] = {
        "audience": "decide_for_me",
        "emphasis": ["decide_for_me"],
        "title_style": "decide_for_me",
        "include_interactive": "decide_for_me",
        "theme": "decide_for_me",
        "speaker_notes": "decide_for_me",
        "diagrams": "decide_for_me",
    }
    resolved = engine.apply_answers(questions, answers)
    # Engineering domain defaults
    assert resolved.audience is AudienceType.UNDERGRADUATE
    assert resolved.title_style is TitleStyle.TAKEAWAY
    assert resolved.background_treatment is BackgroundTreatment.DARK
    assert resolved.diagram_strategy is DiagramStrategy.BUILD_SVG
    assert resolved.include_interactive is False


def test_apply_answers_mixed_explicit_and_defaults() -> None:
    engine = PresentationInterviewEngine()
    questions = engine.generate_questions(
        claims=_engineering_claims(), chunks=[], source_metadata=[]
    )
    answers: dict[str, str | int | bool | list[str]] = {
        "audience": "graduate",
        "emphasis": ["decide_for_me"],
        "theme": "light",  # explicit override of engineering's dark default
    }
    resolved = engine.apply_answers(questions, answers)
    assert resolved.audience is AudienceType.GRADUATE
    assert resolved.narrative_emphasis is NarrativeEmphasis.BALANCED
    assert resolved.background_treatment is BackgroundTreatment.LIGHT


def test_apply_answers_headline_numbers_parsing() -> None:
    engine = PresentationInterviewEngine()
    questions = engine.generate_questions(
        claims=_education_claims() + _stat_claims(3),
        chunks=[],
        source_metadata=[],
    )
    resolved = engine.apply_answers(
        questions,
        {"headline_numbers": "94.4% water, PUE=4055, $1.04M cost"},
    )
    assert resolved.headline_numbers == ["94.4% water", "PUE=4055", "$1.04M cost"]


def test_apply_answers_emphasis_multiple_picks_falls_back_to_balanced() -> None:
    engine = PresentationInterviewEngine()
    questions = engine.generate_questions(claims=_education_claims(), chunks=[], source_metadata=[])
    resolved = engine.apply_answers(
        questions,
        {"emphasis": ["methodology", "results_numbers"]},
    )
    assert resolved.narrative_emphasis is NarrativeEmphasis.BALANCED


def test_apply_defaults_shortcut_returns_valid_answers() -> None:
    engine = PresentationInterviewEngine()
    defaults = engine.apply_defaults(claims=_education_claims(), source_metadata=[])
    assert isinstance(defaults, PresentationInterviewAnswers)
    # Round-trip serialisation guarantees every field has a usable value.
    again = PresentationInterviewAnswers.model_validate(defaults.model_dump(mode="json"))
    assert again == defaults


def test_apply_answers_closing_ask_text_captured() -> None:
    engine = PresentationInterviewEngine()
    questions = engine.generate_questions(claims=_education_claims(), chunks=[], source_metadata=[])
    resolved = engine.apply_answers(
        questions,
        {"closing_ask": "Pilot site at hyperscaler X"},
    )
    assert resolved.closing_ask == "Pilot site at hyperscaler X"
