"""The model registry is the only source of model ids, and its facts hold (B0)."""

from __future__ import annotations

import inspect
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from packages.core.llm import (
    LLMClient,
    claude_request_id,
    request_body_extras,
    thinking_config,
)
from packages.core.model_registry import (
    ENV_OVERRIDES,
    MODELS,
    REFUSED_IDS,
    ROLES,
    ClaudeEffort,
    ClaudeThinking,
    Provider,
    Role,
    Transport,
    UnknownModelError,
    image_cost_usd,
    known_ids,
    lifecycle_risks,
    model_for,
    spec,
    token_cost_usd,
    transport_id,
)

ROOT = Path(__file__).resolve().parents[2]

# Anything shaped like a Claude or Gemini model id.
_MODEL_ID = re.compile(
    r"\b(claude-(?:opus|sonnet|haiku|instant|[0-9])[A-Za-z0-9.@_-]*|gemini-[0-9][A-Za-z0-9._-]*)"
)
# Code and config. Prose (docs, markdown, review notes) may cite history freely.
_SCANNED_SUFFIXES = frozenset(
    {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".json", ".yml", ".yaml", ".toml", ".sql", ".sh"}
)
_SCANNED_NAMES = frozenset({"Dockerfile", "Caddyfile", ".env.example", ".env.local.example"})
_REGISTRY = "packages/core/model_registry.py"
# This file: its scanner fixtures name ids that must stay unregistered.
_SELF = "tests/unit/test_model_registry.py"


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.splitlines()


def _ids_in(path: str) -> set[str]:
    try:
        text = (ROOT / path).read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return set()
    return {match.rstrip(".-_") for match in _MODEL_ID.findall(text)}


def _scanned(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if path.startswith(("docs/", "review/")) or "node_modules/" in path:
        return False
    return name in _SCANNED_NAMES or Path(name).suffix in _SCANNED_SUFFIXES


# ------------------------------------------------------------ unknown ids


def test_no_unknown_model_id_anywhere_in_code_or_config() -> None:
    """Code and config name only registered ids; tests may also name refused ones."""

    files = [path for path in _tracked_files() if _scanned(path)]
    assert len(files) > 100  # the scan really walked the repository
    allowed = known_ids()
    offenders: list[str] = []
    for path in files:
        if path in (_REGISTRY, _SELF):
            continue
        permitted = allowed | set(REFUSED_IDS) if path.startswith("tests/") else allowed
        offenders += [f"{path}: {model_id}" for model_id in sorted(_ids_in(path) - permitted)]
    assert offenders == []


def test_the_scan_recognises_every_id_shape_it_must_catch() -> None:
    sample = (
        'a = "claude-haiku-4-5@20251001"; b = "gemini-3-flash"; '
        "c = 'claude-sonnet-5-5'. d = gemini-3.1-pro-preview, e = claude-3-5-sonnet-20241022"
    )
    found = {match.rstrip(".-_") for match in _MODEL_ID.findall(sample)}
    assert found == {
        "claude-haiku-4-5@20251001",
        "gemini-3-flash",
        "claude-sonnet-5-5",
        "gemini-3.1-pro-preview",
        "claude-3-5-sonnet-20241022",
    }


def test_refused_ids_are_not_registered() -> None:
    assert set(REFUSED_IDS).isdisjoint(known_ids())


@pytest.mark.parametrize("model", sorted(REFUSED_IDS))
def test_every_refused_id_fails_with_its_reason(model: str) -> None:
    with pytest.raises(UnknownModelError, match="is refused"):
        spec(model)


def test_an_unregistered_id_fails() -> None:
    with pytest.raises(UnknownModelError, match="not in packages/core/model_registry"):
        spec("gemini-9-ultra")


# ------------------------------------------------------------ roles


def test_role_table_is_pinned() -> None:
    """The deployed choice per role; changing one is a deliberate edit here too."""

    assert {role: model_for(role) for role in Role} == {
        Role.SLIDE_WRITER: "claude-sonnet-5-5",
        Role.SECTION_DRAFTER: "claude-sonnet-5-5",
        Role.RESEARCH_INTERVIEW: "claude-haiku-5-5",
        Role.ARTICLE_OUTLINE: "claude-haiku-5-5",
        Role.CLAUDE_DEFAULT: "claude-haiku-5-5",
        Role.DECK_PLANNER: "gemini-3.1-pro-preview",
        Role.CONTENT_CRITIC: "gemini-3.1-pro-preview",
        Role.DECK_BRAIN: "gemini-3.1-pro-preview",
        Role.THESIS_CLASSIFIER: "gemini-3.8-flash",
        Role.DESIGN_DIRECTION: "gemini-3.8-flash",
        Role.CLAIM_EXTRACTION: "gemini-3.8-flash",
        Role.INTERACTIVE_CONTENT: "gemini-3.8-flash",
        Role.CITATION_VERIFICATION: "gemini-3.8-flash",
        Role.VISION_CAPTION: "gemini-3.8-flash",
        Role.GEMINI_DEFAULT: "gemini-3.8-flash",
        Role.IMAGE_GENERATION: "gemini-3-pro-image",
    }


def test_every_role_call_site_exists() -> None:
    for role in ROLES.values():
        for path in role.call_sites:
            assert (ROOT / path).is_file(), path


def test_every_model_and_fallback_is_registered_with_the_same_provider() -> None:
    for entry in MODELS.values():
        assert set(entry.ids) == set(
            {
                Provider.ANTHROPIC: (Transport.ANTHROPIC_API, Transport.VERTEX_ANTHROPIC),
                Provider.GOOGLE: (Transport.GEMINI_API, Transport.VERTEX_GEMINI),
            }[entry.provider]
        )
        if entry.fallback is not None:
            assert MODELS[entry.fallback].provider is entry.provider
            assert entry.fallback != entry.key


# ------------------------------------------------------------ lifecycle


def test_no_model_in_use_may_end_within_30_days_without_a_safe_fallback() -> None:
    assert lifecycle_risks(date.today(), horizon_days=30) == []


def test_lifecycle_check_flags_an_unprotected_model_inside_the_horizon() -> None:
    # gemini-3-pro-image records no fallback; 18 days before its earliest end it is a risk.
    end = MODELS["gemini-3-pro-image"].lifecycle.earliest_end
    assert end == date(2027, 5, 28)
    risks = lifecycle_risks(end - timedelta(days=18))
    assert risks == ["gemini-3-pro-image may end 2027-05-28 with no registered fallback"]
    assert lifecycle_risks(end - timedelta(days=31)) == []


def test_lifecycle_check_flags_a_fallback_that_ends_too() -> None:
    # Near Sonnet 5.5's date its fallback (Sonnet 5, 2027-06-30) has ended as well,
    # and Haiku 5.5's fallback is Sonnet 5.5 itself.
    risks = lifecycle_risks(date(2027, 9, 20))
    assert (
        "claude-sonnet-5-5 may end 2027-09-28; its fallback claude-sonnet-5 may end 2027-06-30"
        in risks
    )
    assert (
        "claude-haiku-5-5 may end 2027-10-07; its fallback claude-sonnet-5-5 may end 2027-09-28"
        in risks
    )


def test_recorded_lifecycle_dates() -> None:
    ends = {key: entry.lifecycle.earliest_end for key, entry in MODELS.items()}
    assert ends == {
        "claude-sonnet-5-5": date(2027, 9, 28),
        "claude-sonnet-5": date(2027, 6, 30),
        "claude-haiku-5-5": date(2027, 10, 7),
        "gemini-3.8-flash": None,
        "gemini-3.1-pro-preview": None,
        "gemini-3-pro-image": date(2027, 5, 28),
    }


def test_each_model_in_use_names_its_fallback() -> None:
    assert {key: MODELS[key].fallback for key in {r.model for r in ROLES.values()}} == {
        "claude-sonnet-5-5": "claude-sonnet-5",
        "claude-haiku-5-5": "claude-sonnet-5-5",
        "gemini-3.8-flash": "gemini-3.1-pro-preview",
        "gemini-3.1-pro-preview": "gemini-3.8-flash",
        "gemini-3-pro-image": None,
    }


# ------------------------------------------------------------ transports


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        (Transport.ANTHROPIC_API, "claude-haiku-5-5"),
        (Transport.VERTEX_ANTHROPIC, "claude-haiku-5-5"),
    ],
)
def test_each_claude_transport_gets_its_haiku_spelling(transport: Transport, expected: str) -> None:
    assert transport_id("claude-haiku-5-5", transport) == expected


@pytest.mark.parametrize("transport", [Transport.GEMINI_API, Transport.VERTEX_GEMINI])
def test_haiku_cannot_be_sent_over_a_gemini_transport(transport: Transport) -> None:
    with pytest.raises(UnknownModelError, match="cannot be called over"):
        transport_id("claude-haiku-5-5", transport)


@pytest.mark.parametrize(
    ("llm_transport", "location", "expected"),
    [
        ("anthropic", None, "claude-haiku-5-5"),
        ("vertex", "global", "claude-haiku-5-5"),
        ("vertex", "us", "claude-haiku-5-5"),
        ("vertex", "eu", "claude-haiku-5-5"),
        ("injected", None, "claude-haiku-5-5"),
    ],
)
def test_llm_client_resolves_haiku_per_transport(
    llm_transport: str, location: str | None, expected: str
) -> None:
    assert claude_request_id(model_for(Role.CLAUDE_DEFAULT), llm_transport, location) == expected  # type: ignore[arg-type]


def test_llm_client_refuses_claude_5_on_a_single_vertex_region() -> None:
    with pytest.raises(UnknownModelError, match="us-east5"):
        claude_request_id("claude-haiku-5-5", "vertex", "us-east5")


def test_gemini_is_served_only_from_the_global_vertex_location() -> None:
    assert transport_id("gemini-3.8-flash", Transport.VERTEX_GEMINI, "global") == "gemini-3.8-flash"
    with pytest.raises(UnknownModelError):
        transport_id("gemini-3.8-flash", Transport.VERTEX_GEMINI, "us-central1")


# The per-model thinking table (platform.claude.com build-with-claude/thinking,
# read 2026-10-13): which thinking values each registered Claude model accepts,
# and the effort levels at which it accepts them. Anything else is a 400.
_DOCUMENTED_THINKING: dict[str, dict[ClaudeThinking, frozenset[ClaudeEffort]]] = {
    "claude-sonnet-5-5": {
        ClaudeThinking.BETWEEN_TOOLS: frozenset(ClaudeEffort),  # low/medium/high only
    },
    "claude-haiku-5-5": {
        ClaudeThinking.DISABLED: frozenset(ClaudeEffort),  # "at high effort or below"
    },
    "claude-sonnet-5": {
        ClaudeThinking.DISABLED: frozenset(ClaudeEffort),  # "Thinking off"
    },
}
# Each model's documented default effort (build-with-claude/effort).
_DOCUMENTED_DEFAULT_EFFORT = {
    "claude-sonnet-5-5": ClaudeEffort.HIGH,
    "claude-haiku-5-5": ClaudeEffort.MEDIUM,
    "claude-sonnet-5": ClaudeEffort.HIGH,
}


def test_every_claude_model_sends_a_documented_thinking_and_effort_pair() -> None:
    claude = {key for key, entry in MODELS.items() if entry.provider is Provider.ANTHROPIC}
    assert claude == set(_DOCUMENTED_THINKING)
    for key in claude:
        entry = MODELS[key]
        assert entry.claude_thinking is not None and entry.claude_effort is not None
        accepted = _DOCUMENTED_THINKING[key]
        assert entry.claude_thinking in accepted, key
        assert entry.claude_effort in accepted[entry.claude_thinking], key
        # Pinned to the default: identical to omitting effort, per the effort page.
        assert entry.claude_effort is _DOCUMENTED_DEFAULT_EFFORT[key]


def test_claude_request_extras() -> None:
    assert request_body_extras("claude-haiku-5-5") == {
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "medium"},
    }
    assert request_body_extras("claude-sonnet-5-5") == {
        "thinking": {"type": "between_tools"},
        "output_config": {"effort": "high"},
    }
    # Sonnet 5 (Sonnet 5.5's fallback) answers "between_tools" with a 400.
    assert request_body_extras("claude-sonnet-5") == {
        "thinking": {"type": "disabled"},
        "output_config": {"effort": "high"},
    }
    with pytest.raises(UnknownModelError):
        thinking_config("gemini-3.8-flash")
    with pytest.raises(UnknownModelError):
        request_body_extras("gemini-3.8-flash")


def test_llm_client_default_is_the_registry_role() -> None:
    default = inspect.signature(LLMClient.complete).parameters["model"].default
    assert default == model_for(Role.CLAUDE_DEFAULT)


# ------------------------------------------------------------ env overrides


def test_env_override_names_only_image_generation() -> None:
    assert ENV_OVERRIDES == {"NASHR_IMAGE_MODEL": Role.IMAGE_GENERATION}


def test_image_override_accepts_a_registered_gemini_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NASHR_IMAGE_MODEL", "gemini-3.8-flash")
    assert model_for(Role.IMAGE_GENERATION) == "gemini-3.8-flash"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("gemini-2.5-flash", "NASHR_IMAGE_MODEL: model 'gemini-2.5-flash' is refused"),
        ("imagen-9", "NASHR_IMAGE_MODEL: model 'imagen-9' is not in"),
        ("claude-haiku-5-5", "NASHR_IMAGE_MODEL='claude-haiku-5-5' is not a google model"),
    ],
)
def test_image_override_refuses_anything_else(
    monkeypatch: pytest.MonkeyPatch, value: str, message: str
) -> None:
    monkeypatch.setenv("NASHR_IMAGE_MODEL", value)
    with pytest.raises(UnknownModelError, match=re.escape(message)):
        model_for(Role.IMAGE_GENERATION)


def test_empty_image_override_means_the_registry_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NASHR_IMAGE_MODEL", "  ")
    assert model_for(Role.IMAGE_GENERATION) == "gemini-3-pro-image"


# ------------------------------------------------------------ prices


def test_every_price_row_is_sourced_and_dated() -> None:
    for entry in MODELS.values():
        rows = [entry.price] + ([entry.price.then] if entry.price.then is not None else [])
        for row in rows:
            assert row.source.startswith("https://")
            assert row.retrieved == date(2026, 10, 13)


def test_flash_price_steps_up_on_2027_01_01() -> None:
    before = token_cost_usd("gemini-3.8-flash", 1_000_000, 1_000_000, day=date(2026, 12, 31))
    after = token_cost_usd("gemini-3.8-flash", 1_000_000, 1_000_000, day=date(2027, 1, 1))
    assert before == pytest.approx(0.75 + 3.75)
    assert after == pytest.approx(1.50 + 7.50)


def test_claude_list_prices() -> None:
    day = date(2026, 10, 13)
    assert token_cost_usd("claude-sonnet-5-5", 1_000_000, 1_000_000, day=day) == pytest.approx(12.0)
    assert token_cost_usd("claude-haiku-5-5", 100_000, 1_000_000, day=day) == pytest.approx(0.51)
    # One token over the 100k threshold moves the whole call to the long-context tier.
    assert token_cost_usd("claude-haiku-5-5", 100_001, 0, day=day) == pytest.approx(
        100_001 * 0.50 / 1_000_000
    )


def test_image_price() -> None:
    assert image_cost_usd("gemini-3-pro-image", day=date(2026, 10, 13)) == pytest.approx(0.134)
    with pytest.raises(UnknownModelError, match="no per-image price"):
        image_cost_usd("gemini-3.8-flash")
