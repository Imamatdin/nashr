"""Every model the platform calls, by logical role, with lifecycle and price (B0).

Call sites never write a model id: they ask :func:`model_for` for their role and
get the canonical id; the transport adapters (``LLMClient``, ``GeminiClient``,
the image client) translate it with :func:`transport_id`, which also refuses an
unknown id and a location the model is not served from.

Facts were checked on 2026-10-13 against the official pages cited in each row
(``Price.source`` / ``Lifecycle.source``). Google's Vertex lifecycle and pricing
tables render client-side; where only Google's own indexed text of those pages
could be read, the row says so (``verified="google-index"``).

Why these models (B0):
* Claude moved to the 5.5 generation. Sonnet 4.6 is legacy and Haiku 4.5's
  retirement commitment ends 2026-10-15. Both 5.5 models think by default, so
  each records the thinking mode that reproduces the previous single-pass
  behaviour (``ClaudeThinking``) and pins its effort (``ClaudeEffort``) to the
  documented default, at which that mode is accepted. Per the thinking page's
  per-model table (build-with-claude/thinking, read 2026-10-13): Sonnet 5.5
  rejects "disabled" and accepts "between_tools" at effort high or below; Haiku
  5.5 and Sonnet 5 accept "disabled" (Haiku at effort high or below). Thinking
  counts toward max_tokens (build-with-claude/thinking-steering-and-cost, "Cost
  control"), and the 5.x tokenizer counts "approximately 30% more tokens" for
  the same text than Haiku 4.5 (models/haiku-5-5/overview); Claude budgets were
  scaled x1.3 for that.
* No Claude call forces a tool: Sonnet 5.5 rejects tool_choice "any"/"tool"
  with a 400 error (models/sonnet-5-5/overview). Every Claude call site asks for
  JSON in text, validates it, and retries once with a repair prompt.
* Flash moved to ``gemini-3.8-flash``. ``gemini-3.5-flash`` silently routes to
  ``gemini-3.6-flash`` (billed at 3.6's rate), which Vertex retires 2026-11-19
  with 3.8 Flash as the named upgrade; ``gemini-2.5-flash`` retires on Vertex
  2026-10-20 and the Flash-Lite preview shut down 2026-05-25.
"""

from __future__ import annotations

import os
from datetime import date
from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

RETRIEVED: Final[date] = date(2026, 10, 13)

_CLAUDE_PRICING = "https://platform.claude.com/docs/en/about-claude/pricing"
_CLAUDE_LIFECYCLE = "https://platform.claude.com/docs/en/about-claude/model-deprecations"
_GEMINI_PRICING = "https://ai.google.dev/gemini-api/docs/pricing"
_VERTEX_PRICING = "https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing"
_GEMINI_LIFECYCLE = "https://ai.google.dev/gemini-api/docs/deprecations"
_VERTEX_LIFECYCLE = (
    "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions"
)


class Provider(StrEnum):
    """Who makes the model."""

    ANTHROPIC = "anthropic"
    GOOGLE = "google"


class Transport(StrEnum):
    """How a call reaches the model."""

    ANTHROPIC_API = "anthropic_api"
    VERTEX_ANTHROPIC = "vertex_anthropic"
    GEMINI_API = "gemini_api"
    VERTEX_GEMINI = "vertex_gemini"


PROVIDER_TRANSPORTS: Final[dict[Provider, tuple[Transport, ...]]] = {
    Provider.ANTHROPIC: (Transport.ANTHROPIC_API, Transport.VERTEX_ANTHROPIC),
    Provider.GOOGLE: (Transport.GEMINI_API, Transport.VERTEX_GEMINI),
}


class ClaudeThinking(StrEnum):
    """The ``thinking`` setting sent with every request to a Claude model."""

    DISABLED = "disabled"  # Haiku 5.5 (effort <= high), Sonnet 5: thinking off
    BETWEEN_TOOLS = "between_tools"  # Sonnet 5.5 only: no up-front thinking (effort <= high)


class ClaudeEffort(StrEnum):
    """``output_config.effort`` sent with every request to a Claude model."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Price(BaseModel):
    """USD per million tokens (or per image), as published on ``retrieved``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input: float
    output: float
    cache_read: float | None = None
    cache_write_5m: float | None = None
    cache_write_1h: float | None = None
    # Prompts longer than this many input tokens are billed at the long rates.
    long_context_threshold: int | None = None
    long_input: float | None = None
    long_output: float | None = None
    per_image: float | None = None
    # A scheduled change: this row applies through ``until``, then ``then``.
    until: date | None = None
    then: Price | None = None
    source: str
    retrieved: date = RETRIEVED
    verified: Literal["official-page", "google-index"] = "official-page"

    def on(self, day: date) -> Price:
        """The row in force on ``day``."""

        if self.until is not None and self.then is not None and day > self.until:
            return self.then.on(day)
        return self


class Lifecycle(BaseModel):
    """When the model may stop working on the transports we use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Anthropic: "not sooner than"; Google: an announced retirement date.
    earliest_end: date | None
    kind: Literal["not_before", "retires_on", "none_announced"]
    source: str
    verified: Literal["official-page", "google-index"] = "official-page"


class ModelSpec(BaseModel):
    """One model: its id on every transport, where it is served, lifecycle, price."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    provider: Provider
    ids: dict[Transport, str]
    # Vertex locations the provider serves it from (availability, not policy;
    # DEPLOYED_VERTEX_LOCATIONS is the policy).
    vertex_locations: tuple[str, ...]
    lifecycle: Lifecycle
    fallback: str | None
    price: Price
    claude_thinking: ClaudeThinking | None = None
    claude_effort: ClaudeEffort | None = None


class Role(StrEnum):
    """A call purpose. Each call site resolves its model through its role."""

    SLIDE_WRITER = "slide_writer"
    SECTION_DRAFTER = "section_drafter"
    RESEARCH_INTERVIEW = "research_interview"
    ARTICLE_OUTLINE = "article_outline"
    CLAUDE_DEFAULT = "claude_default"
    DECK_PLANNER = "deck_planner"
    CONTENT_CRITIC = "content_critic"
    DECK_BRAIN = "deck_brain"
    THESIS_CLASSIFIER = "thesis_classifier"
    DESIGN_DIRECTION = "design_direction"
    CLAIM_EXTRACTION = "claim_extraction"
    INTERACTIVE_CONTENT = "interactive_content"
    CITATION_VERIFICATION = "citation_verification"
    VISION_CAPTION = "vision_caption"
    GEMINI_DEFAULT = "gemini_default"
    IMAGE_GENERATION = "image_generation"


class RoleSpec(BaseModel):
    """What a role is for, where it is called, and the model it uses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    purpose: str
    call_sites: tuple[str, ...]


_SONNET_5_5 = "claude-sonnet-5-5"
_SONNET_5 = "claude-sonnet-5"
_HAIKU_5_5 = "claude-haiku-5-5"
_FLASH = "gemini-3.8-flash"
_PRO = "gemini-3.1-pro-preview"
_IMAGE = "gemini-3-pro-image"

_CLAUDE_VERTEX_LOCATIONS = ("global", "us", "eu")  # 5.x: no single-region endpoints

# Deployment policy: the only Vertex location Nashr calls. The us / eu
# multi-regions are served but unsupported here for two reasons: anthropic 0.84's
# AsyncAnthropicVertex builds https://{region}-aiplatform.googleapis.com for them,
# while Google serves multi-regions at https://aiplatform.{region}.rep.googleapis.com;
# and multi-region calls bill 1.1x, which these price rows do not model. Refusing
# them keeps every accepted call on a working endpoint at a correct price.
DEPLOYED_VERTEX_LOCATIONS: Final[tuple[str, ...]] = ("global",)


def _claude(
    key: str,
    not_before: date,
    fallback: str | None,
    price: Price,
    thinking: ClaudeThinking,
    effort: ClaudeEffort,
) -> ModelSpec:
    return ModelSpec(
        key=key,
        provider=Provider.ANTHROPIC,
        # Since the 4.6 generation the Claude API and Vertex ids are identical.
        ids={Transport.ANTHROPIC_API: key, Transport.VERTEX_ANTHROPIC: key},
        vertex_locations=_CLAUDE_VERTEX_LOCATIONS,
        lifecycle=Lifecycle(earliest_end=not_before, kind="not_before", source=_CLAUDE_LIFECYCLE),
        fallback=fallback,
        price=price,
        claude_thinking=thinking,
        claude_effort=effort,
    )


def _gemini(
    key: str,
    lifecycle: Lifecycle,
    fallback: str | None,
    price: Price,
    served: tuple[str, ...] = ("global",),
) -> ModelSpec:
    return ModelSpec(
        key=key,
        provider=Provider.GOOGLE,
        ids={Transport.GEMINI_API: key, Transport.VERTEX_GEMINI: key},
        vertex_locations=served,
        lifecycle=lifecycle,
        fallback=fallback,
        price=price,
    )


MODELS: Final[dict[str, ModelSpec]] = {
    spec.key: spec
    for spec in (
        _claude(
            _SONNET_5_5,
            date(2027, 9, 28),
            _SONNET_5,
            Price(
                input=2.0,
                output=10.0,
                cache_read=0.10,
                cache_write_5m=2.50,
                cache_write_1h=4.0,
                source=_CLAUDE_PRICING,
            ),
            ClaudeThinking.BETWEEN_TOOLS,
            ClaudeEffort.HIGH,  # the documented default
        ),
        _claude(
            _SONNET_5,
            date(2027, 6, 30),
            None,
            Price(
                input=2.0,
                output=10.0,
                cache_read=0.20,
                cache_write_5m=2.50,
                cache_write_1h=4.0,
                source=_CLAUDE_PRICING,
            ),
            # Sonnet 5 answers "between_tools" with a 400; it takes "disabled".
            ClaudeThinking.DISABLED,
            ClaudeEffort.HIGH,  # the documented default
        ),
        _claude(
            _HAIKU_5_5,
            date(2027, 10, 7),
            _SONNET_5_5,
            Price(
                input=0.10,
                output=0.50,
                cache_read=0.01,
                cache_write_5m=0.125,
                cache_write_1h=0.20,
                long_context_threshold=100_000,
                long_input=0.50,
                long_output=2.50,
                source=_CLAUDE_PRICING,
            ),
            ClaudeThinking.DISABLED,
            ClaudeEffort.MEDIUM,  # the documented default
        ),
        _gemini(
            _FLASH,
            Lifecycle(
                earliest_end=None,
                kind="none_announced",
                source=_VERTEX_LIFECYCLE,
                verified="google-index",
            ),
            _PRO,
            Price(
                input=0.75,
                output=3.75,
                until=date(2026, 12, 31),
                then=Price(
                    input=1.50, output=7.50, source=_VERTEX_PRICING, verified="google-index"
                ),
                source=_VERTEX_PRICING,
                verified="google-index",
            ),
            served=("global", "us", "eu"),  # Vertex 3-8-flash model page, 2026-10-13
        ),
        _gemini(
            _PRO,
            Lifecycle(earliest_end=None, kind="none_announced", source=_GEMINI_LIFECYCLE),
            _FLASH,
            Price(
                input=2.0,
                output=12.0,
                long_context_threshold=200_000,
                long_input=4.0,
                long_output=18.0,
                source=_GEMINI_PRICING,
            ),
        ),
        _gemini(
            _IMAGE,
            Lifecycle(
                earliest_end=date(2027, 5, 28),
                kind="not_before",
                source=_VERTEX_LIFECYCLE,
                verified="google-index",
            ),
            None,
            # 1K/2K output image; 4K images cost 0.24 and are not requested.
            Price(input=2.0, output=12.0, per_image=0.134, source=_GEMINI_PRICING),
        ),
    )
}


ROLES: Final[dict[Role, RoleSpec]] = {
    Role.SLIDE_WRITER: RoleSpec(
        model=_SONNET_5_5,
        purpose="editorial executor: writes every slide of a deck",
        call_sites=("packages/presentation/editorial.py",),
    ),
    Role.SECTION_DRAFTER: RoleSpec(
        model=_SONNET_5_5,
        purpose="drafts and revises article sections with citations",
        call_sites=("packages/workers/article/drafter.py",),
    ),
    Role.RESEARCH_INTERVIEW: RoleSpec(
        model=_HAIKU_5_5,
        purpose="generates research questions and scores answers",
        call_sites=("packages/workers/article/interview.py",),
    ),
    Role.ARTICLE_OUTLINE: RoleSpec(
        model=_HAIKU_5_5,
        purpose="builds the article outline from the evidence matrix",
        call_sites=("packages/workers/article/outline_generator.py",),
    ),
    Role.CLAUDE_DEFAULT: RoleSpec(
        model=_HAIKU_5_5,
        purpose="LLMClient / ModelRouter default when a caller names no model",
        call_sites=("packages/core/llm.py", "packages/core/model_router.py"),
    ),
    Role.DECK_PLANNER: RoleSpec(
        model=_PRO,
        purpose="source-grounded authorship plan for a deck",
        call_sites=("packages/presentation/planner.py",),
    ),
    Role.CONTENT_CRITIC: RoleSpec(
        model=_PRO,
        purpose="adversarial source-grounding audit of a finished deck",
        call_sites=("packages/presentation/content_critic.py",),
    ),
    Role.DECK_BRAIN: RoleSpec(
        model=_PRO,
        purpose="chat brain: tool-calling slide edits and its context cache",
        call_sites=("packages/core/gemini.py", "packages/core/gemini_cache.py"),
    ),
    Role.THESIS_CLASSIFIER: RoleSpec(
        model=_FLASH,
        purpose="classifies the deck thesis for the planner validator",
        call_sites=("packages/presentation/thesis_classifier.py",),
    ),
    Role.DESIGN_DIRECTION: RoleSpec(
        model=_FLASH,
        purpose="picks palette, fonts and mood for a deck",
        call_sites=("packages/presentation/design_direction.py",),
    ),
    Role.CLAIM_EXTRACTION: RoleSpec(
        model=_FLASH,
        purpose="extracts claims from source passages",
        call_sites=("packages/workers/source/claim_extractor.py",),
    ),
    Role.INTERACTIVE_CONTENT: RoleSpec(
        model=_FLASH,
        purpose="writes quizzes and exercises for interactive slides",
        call_sites=("packages/presentation/editorial.py",),
    ),
    Role.CITATION_VERIFICATION: RoleSpec(
        model=_FLASH,
        purpose="checks that each cited passage supports its claim",
        call_sites=("packages/workers/article/citation_verifier.py",),
    ),
    Role.VISION_CAPTION: RoleSpec(
        model=_FLASH,
        purpose="captions figures and images found in sources",
        call_sites=("packages/core/gemini_image.py",),
    ),
    Role.GEMINI_DEFAULT: RoleSpec(
        model=_FLASH,
        purpose="GeminiClient default when a caller names no model",
        call_sites=("packages/core/gemini.py",),
    ),
    Role.IMAGE_GENERATION: RoleSpec(
        model=_IMAGE,
        purpose="generates slide images (overridable by NASHR_IMAGE_MODEL)",
        call_sites=("packages/core/gemini_image.py",),
    ),
}


# Ids this codebase used or might reach for, and why each is refused. Only tests
# (proving the refusal) and this module may name them; the scan in
# tests/unit/test_model_registry.py fails on any other mention in code or config.
REFUSED_IDS: Final[dict[str, str]] = {
    "claude-haiku-4-5-20251001": "Haiku 4.5: retirement commitment ends 2026-10-15; use claude-haiku-5-5",
    "claude-haiku-4-5@20251001": "Haiku 4.5 (Vertex spelling): see claude-haiku-4-5-20251001",
    "claude-sonnet-4-6": "legacy generation; use claude-sonnet-5-5",
    "claude-sonnet-4-6-20250514": "never a model id: -20250514 is Sonnet 4's date suffix",
    "claude-sonnet-4-20250514": "Sonnet 4: retired 2026-06-15",
    "claude-opus-4-8": "Opus is never used for runtime user jobs",
    "gemini-3-flash": "never a model id: the preview is gemini-3-flash-preview",
    "gemini-2.5-flash": "Vertex retires it 2026-10-20 (successor gemini-3.8-flash)",
    "gemini-3.5-flash": "silently routes to gemini-3.6-flash, which Vertex retires 2026-11-19",
    "gemini-3.6-flash": "Vertex retires it 2026-11-19 (successor gemini-3.8-flash)",
    "gemini-3.1-flash-lite-preview": "shut down 2026-05-25",
}


class UnknownModelError(ValueError):
    """A model id, transport or location that the registry does not list."""


# Deployment env vars that may replace a role's model. Each value must be a
# registered model from the same provider; anything else fails at resolution.
ENV_OVERRIDES: Final[dict[str, Role]] = {"NASHR_IMAGE_MODEL": Role.IMAGE_GENERATION}


def model_for(role: Role) -> str:
    """The model id for ``role``: its env override if one is set, else the registry's."""

    default = ROLES[role].model
    for env_var, overridden in ENV_OVERRIDES.items():
        value = os.environ.get(env_var, "").strip()
        if overridden is not role or not value:
            continue
        try:
            entry = spec(value)
        except UnknownModelError as exc:
            raise UnknownModelError(f"{env_var}: {exc}") from exc
        if entry.provider is not spec(default).provider:
            raise UnknownModelError(f"{env_var}={value!r} is not a {spec(default).provider} model")
        if role is Role.IMAGE_GENERATION and entry.price.per_image is None:
            raise UnknownModelError(f"{env_var}={value!r} is not an image model")
        return entry.key
    return default


def spec(model: str) -> ModelSpec:
    """The registry row for a canonical id or any transport-specific id."""

    if model in MODELS:
        return MODELS[model]
    for candidate in MODELS.values():
        if model in candidate.ids.values():
            return candidate
    if model in REFUSED_IDS:
        raise UnknownModelError(f"model {model!r} is refused: {REFUSED_IDS[model]}")
    raise UnknownModelError(f"model {model!r} is not in packages/core/model_registry.py")


def transport_id(model: str, transport: Transport, location: str | None = None) -> str:
    """The id to send on ``transport``; refuses unknown models, transports and locations."""

    entry = spec(model)
    if transport not in PROVIDER_TRANSPORTS[entry.provider]:
        raise UnknownModelError(f"{entry.key} ({entry.provider}) cannot be called over {transport}")
    is_vertex = transport in (Transport.VERTEX_ANTHROPIC, Transport.VERTEX_GEMINI)
    if is_vertex and location is not None:
        if location not in entry.vertex_locations:
            raise UnknownModelError(
                f"{entry.key} is not served from Vertex location {location!r};"
                f" use one of {entry.vertex_locations}"
            )
        if location not in DEPLOYED_VERTEX_LOCATIONS:
            raise UnknownModelError(
                f"Vertex location {location!r} serves {entry.key} but is not deployed: see"
                f" DEPLOYED_VERTEX_LOCATIONS (use one of {DEPLOYED_VERTEX_LOCATIONS})"
            )
    return entry.ids[transport]


def known_ids() -> frozenset[str]:
    """Every id the registry accepts, on any transport."""

    return frozenset(i for entry in MODELS.values() for i in (entry.key, *entry.ids.values()))


def token_cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cache_read_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    day: date | None = None,
) -> float:
    """USD for one call from its token usage, at the rates in force on ``day``."""

    price = spec(model).price.on(day or date.today())
    prompt = input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens
    long = price.long_context_threshold is not None and prompt > price.long_context_threshold
    scale = 1.0
    input_rate, output_rate = price.input, price.output
    if long and price.long_input is not None and price.long_output is not None:
        scale = price.long_input / price.input
        input_rate, output_rate = price.long_input, price.long_output
    total = input_tokens * input_rate + output_tokens * output_rate
    # Cache rates scale with the long-context tier the same way the base rate does.
    total += (
        cache_read_tokens
        * (price.cache_read if price.cache_read is not None else price.input)
        * scale
    )
    total += cache_write_5m_tokens * (price.cache_write_5m or price.input) * scale
    total += cache_write_1h_tokens * (price.cache_write_1h or price.input) * scale
    return total / 1_000_000.0


def image_cost_usd(model: str, day: date | None = None) -> float:
    """USD for one generated image."""

    per_image = spec(model).price.on(day or date.today()).per_image
    if per_image is None:
        raise UnknownModelError(f"{model} has no per-image price")
    return per_image


def lifecycle_risks(today: date, horizon_days: int = 30) -> list[str]:
    """Models used by a role (or as a fallback) that may end within the horizon unprotected.

    A model whose earliest end is within ``horizon_days`` of ``today`` is a risk
    unless it records a fallback that is itself registered and safe.
    """

    in_use = {role.model for role in ROLES.values()}
    in_use |= {f for m in in_use if (f := MODELS[m].fallback) is not None}
    risks: list[str] = []
    for key in sorted(in_use):
        entry = MODELS[key]
        end = entry.lifecycle.earliest_end
        if end is None or (end - today).days > horizon_days:
            continue
        fallback = entry.fallback
        if fallback is None or fallback not in MODELS:
            risks.append(f"{key} may end {end} with no registered fallback")
            continue
        fallback_end = MODELS[fallback].lifecycle.earliest_end
        if fallback_end is not None and (fallback_end - today).days <= horizon_days:
            risks.append(f"{key} may end {end}; its fallback {fallback} may end {fallback_end}")
    return risks


__all__ = [
    "DEPLOYED_VERTEX_LOCATIONS",
    "ENV_OVERRIDES",
    "MODELS",
    "PROVIDER_TRANSPORTS",
    "REFUSED_IDS",
    "RETRIEVED",
    "ROLES",
    "ClaudeEffort",
    "ClaudeThinking",
    "Lifecycle",
    "ModelSpec",
    "Price",
    "Provider",
    "Role",
    "RoleSpec",
    "Transport",
    "UnknownModelError",
    "image_cost_usd",
    "known_ids",
    "lifecycle_risks",
    "model_for",
    "spec",
    "token_cost_usd",
    "transport_id",
]
