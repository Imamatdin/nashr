"""Structural tests for the presentation Mini App HTML page.

The Mini App is a static HTML file served by the bot's webhook server.
These tests assert the structural and behavioural guarantees the bot
handler relies on: the file exists, includes the Telegram SDK, defines
every label key in every supported language, renders all 10 questions,
treats conditional questions as conditional, has no extra external
dependencies, and prevents XSS via an ``esc()`` helper.

The tests intentionally stop short of running the JavaScript inside a
real browser. Instead they parse the file as text and verify the
contracts that handler-side Python code depends on. The end-to-end
"open in Telegram, fill out, submit" path is exercised in the
companion ``test_presentation_flow_mini_app.py`` against the handler
that receives the ``sendData`` payload.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MINI_APP_PATH: Path = Path("packages/bot/mini_app/presentation_questionnaire.html")


@pytest.fixture(scope="module")
def html_content() -> str:
    assert MINI_APP_PATH.exists(), f"Mini App file missing at {MINI_APP_PATH}"
    return MINI_APP_PATH.read_text(encoding="utf-8")


def test_mini_app_file_exists() -> None:
    assert MINI_APP_PATH.exists()
    assert MINI_APP_PATH.is_file()


def test_mini_app_is_valid_html(html_content: str) -> None:
    assert "<!DOCTYPE html>" in html_content
    assert "<html" in html_content
    assert "</html>" in html_content
    assert "<head>" in html_content and "</head>" in html_content
    assert "<body>" in html_content and "</body>" in html_content


def test_mini_app_includes_telegram_sdk(html_content: str) -> None:
    assert "telegram-web-app.js" in html_content
    assert "https://telegram.org/js/telegram-web-app.js" in html_content


def test_mini_app_has_all_4_languages(html_content: str) -> None:
    assert "var LABELS" in html_content
    for code in ("'uz'", "'ru'", "'en'", "'kaa'"):
        assert code in html_content, f"language code {code} missing from LABELS"


def test_mini_app_each_language_has_all_required_label_keys(html_content: str) -> None:
    """Every language block must define every label the JS reads.

    If a key is missing from one language, the corresponding ``L.foo``
    access at render time becomes ``undefined`` and the UI ends up
    blank for that user. Catching missing keys here means the test
    fails before any user sees it.
    """

    required_keys = [
        "title",
        "submit",
        "decide",
        "audience",
        "audience_school",
        "audience_undergrad",
        "audience_grad",
        "audience_conference",
        "audience_mixed",
        "audience_professional",
        "audience_public",
        "duration",
        "duration_hint",
        "emphasis",
        "emphasis_problem",
        "emphasis_technical",
        "emphasis_methodology",
        "emphasis_results",
        "emphasis_roadmap",
        "title_style",
        "title_topic",
        "title_takeaway",
        "interactive",
        "interactive_yes",
        "interactive_no",
        "theme",
        "theme_light",
        "theme_dark",
        "notes",
        "notes_full",
        "notes_brief",
        "notes_none",
        "headline",
        "headline_help",
        "closing",
        "closing_help",
        "diagrams",
        "diagrams_svg",
        "diagrams_placeholder",
        "diagrams_minimal",
    ]

    # One language block per code. Look at each block; ensure every key
    # appears as ``key:`` inside it.
    for code in ("uz", "ru", "en", "kaa"):
        match = re.search(
            rf"'{code}'\s*:\s*\{{(.*?)\}}\s*,?\s*(?:'[a-z]+'|}};)",
            html_content,
            re.DOTALL,
        )
        assert match is not None, f"could not locate {code} block"
        block = match.group(1)
        for key in required_keys:
            assert re.search(rf"\b{key}\s*:", block), f"label key {key!r} missing from {code} block"


def test_mini_app_has_submit_function(html_content: str) -> None:
    assert "function submitAnswers" in html_content
    assert "sendData" in html_content
    assert "JSON.stringify" in html_content


def test_mini_app_has_all_10_questions(html_content: str) -> None:
    expected_state_keys = [
        "audience",
        "duration",
        "emphasis",
        "title_style",
        "include_interactive",
        "theme",
        "speaker_notes",
        "headline_numbers",
        "closing_ask",
        "diagrams",
    ]
    for key in expected_state_keys:
        assert key in html_content, f"question/state key {key!r} not found"


def test_mini_app_submit_payload_includes_all_fields(html_content: str) -> None:
    """The JSON payload sent to the bot must include every answer field."""

    payload_keys = [
        "project_id",
        "audience",
        "talk_duration_minutes",
        "narrative_emphasis",
        "title_style",
        "include_interactive",
        "theme",
        "speaker_notes",
        "headline_numbers",
        "closing_ask",
        "diagrams",
    ]
    for key in payload_keys:
        assert f"{key}:" in html_content, f"payload field {key!r} missing"


def test_mini_app_headline_question_is_conditional_on_stats(html_content: str) -> None:
    assert re.search(r"if\s*\(\s*availableStats\s*>\s*0\s*\)", html_content), (
        "headline_numbers question must be gated by availableStats > 0"
    )


def test_mini_app_closing_ask_hidden_by_default(html_content: str) -> None:
    assert "q-closing" in html_content
    assert "closingQ.classList.add('hidden')" in html_content


def test_mini_app_diagrams_question_is_conditional_on_domain(html_content: str) -> None:
    assert "techDomains" in html_content
    for domain in ("engineering", "computer_science", "medical"):
        assert f"'{domain}'" in html_content, f"technical domain {domain!r} missing"


def test_mini_app_no_external_dependencies_other_than_telegram(html_content: str) -> None:
    """Only one external script tag may exist: the Telegram SDK."""

    script_srcs = re.findall(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', html_content)
    assert script_srcs == ["https://telegram.org/js/telegram-web-app.js"], (
        f"unexpected external scripts: {script_srcs!r}"
    )
    # No stylesheet links either — all CSS is inline.
    link_hrefs = re.findall(
        r'<link\b[^>]*\brel\s*=\s*["\']stylesheet["\'][^>]*\bhref\s*=\s*["\']([^"\']+)["\']',
        html_content,
    )
    assert link_hrefs == [], f"unexpected external stylesheets: {link_hrefs!r}"


def test_mini_app_has_esc_function(html_content: str) -> None:
    """XSS prevention: the page renders text via ``textContent``.

    An ``esc()`` helper is also defined so a future contributor reaching
    for ``innerHTML`` interpolation has a ready-made escape function.
    The primary defence, however, is that the current implementation
    never interpolates user-controlled values into ``innerHTML`` — it
    sets every label, option, and value via ``textContent``, which the
    DOM treats as inert text.
    """

    assert "function esc(" in html_content
    assert "textContent" in html_content
    # Negative guard: no template-string interpolation into innerHTML.
    assert "innerHTML = `" not in html_content
    assert 'innerHTML = "${' not in html_content


def test_mini_app_reads_all_query_params(html_content: str) -> None:
    assert "URLSearchParams" in html_content
    for param in ("lang", "project_id", "stats", "people", "domain"):
        assert f"params.get('{param}')" in html_content, f"query param {param!r} not read"


def test_mini_app_applies_telegram_theme(html_content: str) -> None:
    """All eight Telegram theme params are wired to CSS variables."""

    theme_vars = [
        "bg_color",
        "text_color",
        "hint_color",
        "link_color",
        "button_color",
        "button_text_color",
        "secondary_bg_color",
    ]
    for var in theme_vars:
        assert f"theme.{var}" in html_content, f"theme.{var} not applied"
    assert "--tg-theme-bg-color" in html_content


def test_mini_app_decide_for_me_is_present_per_question(html_content: str) -> None:
    """Every single/multi-select question must include a decide_for_me option."""

    # decide_for_me appears once in state initializers, plus once per option
    # list for the seven select-style questions (audience, emphasis,
    # title_style, include_interactive, theme, speaker_notes, diagrams).
    occurrences = html_content.count("'decide_for_me'")
    assert occurrences >= 8, (
        f"decide_for_me only appears {occurrences} times; expected one per "
        "select-style question plus state defaults"
    )


def test_mini_app_emphasis_supports_multi_select(html_content: str) -> None:
    """The narrative-emphasis question caps at 2 selections."""

    assert "buildMultiSelect('emphasis'" in html_content
    # The max-selection argument is passed positionally; the question uses 2.
    assert re.search(
        r"buildMultiSelect\(\s*'emphasis'[^)]*,\s*2\s*\)",
        html_content,
        re.DOTALL,
    ), "emphasis question must cap multi-select at 2"


def test_mini_app_slider_question_has_duration_range(html_content: str) -> None:
    assert re.search(
        r"buildSlider\(\s*'duration'[^)]*,\s*5\s*,\s*45\s*,\s*15\s*,",
        html_content,
        re.DOTALL,
    ), "duration slider must run from 5 to 45 with default 15"


def test_mini_app_submits_via_telegram_send_data(html_content: str) -> None:
    """The submit handler must actually call ``tg.sendData(jsonStr)``."""

    assert "tg.sendData(jsonStr)" in html_content
