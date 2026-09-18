"""Output language survives answering and skipping the presentation interview."""

import pytest

from packages.core.enums import Language
from packages.presentation.interview import PresentationInterviewEngine


@pytest.mark.parametrize("language", [Language.UZ, Language.RU, Language.EN])
def test_answering_interview_preserves_requested_language(language: Language) -> None:
    """Answering preferences must not silently reset the output language."""
    engine = PresentationInterviewEngine()
    questions = engine.generate_questions(
        claims=[], chunks=[], source_metadata=[], language=language
    )
    result = engine.apply_answers(questions, {"duration": 20}, language=language)
    assert result.language is language
    assert result.talk_duration_minutes == 20


@pytest.mark.parametrize("language", [Language.UZ, Language.RU, Language.EN])
def test_skipping_interview_preserves_requested_language(language: Language) -> None:
    """Default preferences must retain the explicitly requested language."""
    result = PresentationInterviewEngine().apply_defaults([], [], language=language)
    assert result.language is language
