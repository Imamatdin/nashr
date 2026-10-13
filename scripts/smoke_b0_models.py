"""B0 paid smoke test: every model role, a few real calls on the real transport.

Usage (from the repo root, with .env holding VERTEX_PROJECT / LLM_TRANSPORT):

    python scripts/smoke_b0_models.py --dry-run      # no network, fake clients
    python scripts/smoke_b0_models.py --spend        # REAL calls; hard cap $5
    python scripts/smoke_b0_models.py --haiku-only   # REAL Haiku 5.5 calls, Claude API

``--haiku-only`` runs only claude-haiku-5-5 over the direct Claude API
(LLM_TRANSPORT=anthropic): the Haiku roles, plus the real editorial prompt in
the four languages with Haiku standing in for Sonnet 5.5. Those editorial rows
prove the request shape, language handling and JSON contract, not Sonnet.

Per call it records model, transport, latency, input / output / thinking tokens,
cost from the registry, JSON validity and truncation, and prints one table.
The editorial probe is the real single-slide path (``regenerate_slide_content``)
on a saved deck, once per language (uz, ru, kaa, en); no full deck is generated.
Before each call the worst case (prompt tokens at ~1 token per 2 chars plus the
full max_tokens) is priced from the registry; a call that could cross the cap
is skipped, so total spend can never exceed it.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from google.genai import types as genai_types  # noqa: E402

from packages.core.enums import Language  # noqa: E402
from packages.core.gemini import GeminiClient, gemini_request_id  # noqa: E402
from packages.core.gemini_image import GeminiImageClient  # noqa: E402
from packages.core.llm import LLMClient, LLMResponse  # noqa: E402
from packages.core.model_registry import (  # noqa: E402
    Role,
    image_cost_usd,
    model_for,
    spec,
    token_cost_usd,
)
from packages.core.models.presentation import DeckSpec  # noqa: E402
from packages.presentation.editorial import EditorialPass  # noqa: E402

HARD_CAP_USD = 5.00
DECK_PATH = ROOT / "gate_b_regen_deck.json"


class BudgetExceededError(RuntimeError):
    """The next call's worst case would cross the hard cap."""


@dataclass
class Row:
    probe: str
    role: str
    model: str
    transport: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    thinking_tokens: int
    cost_usd: float
    json_valid: str
    truncated: str
    note: str = ""


class Ledger:
    """Spend so far, the worst-case gate, and the result rows."""

    def __init__(self, cap: float) -> None:
        self.cap = cap
        self.spent = 0.0
        self.rows: list[Row] = []
        self.current_probe = ""
        self.current_role = ""

    def admit(self, model: str, prompt_chars: int, max_tokens: int) -> None:
        worst = token_cost_usd(model, prompt_chars // 2 + 1, max_tokens)
        if self.spent + worst > self.cap:
            raise BudgetExceededError(
                f"{self.current_probe}: worst case ${worst:.4f} would cross the cap "
                f"(spent ${self.spent:.4f} of ${self.cap:.2f})"
            )

    def record(self, response: LLMResponse, transport: str, json_valid: str) -> None:
        self.spent += response.estimated_cost_usd
        truncated = response.stop_reason in {"max_tokens", "MAX_TOKENS"}
        self.rows.append(
            Row(
                self.current_probe,
                self.current_role,
                response.model,
                transport,
                response.latency_ms,
                response.input_tokens
                + response.cache_read_input_tokens
                + response.cache_creation_input_tokens,
                response.output_tokens,
                response.thinking_tokens,
                response.estimated_cost_usd,
                json_valid,
                f"yes ({response.stop_reason})" if truncated else f"no ({response.stop_reason})",
            )
        )


def _json_valid(text: str) -> str:
    """Whether the text holds one parseable JSON object or array (fences allowed)."""

    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        json.loads(body)
    except ValueError:
        match = re.search(r"[\[{].*[\]}]", body, re.DOTALL)
        if match is None:
            return "no"
        try:
            json.loads(match.group(0))
        except ValueError:
            return "no"
        return "yes (embedded)"
    return "yes"


class RecordingLLM(LLMClient):
    """LLMClient that passes the budget gate before, and records after, every call."""

    def __init__(self, ledger: Ledger, *, stand_in: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ledger = ledger
        self.stand_in = stand_in

    async def complete(self, system: str, user: str, **kwargs: Any) -> LLMResponse:  # type: ignore[override]
        if self.stand_in is not None:
            kwargs["model"] = self.stand_in
        model = kwargs.get("model") or model_for(Role.CLAUDE_DEFAULT)
        self.ledger.admit(model, len(system) + len(user), kwargs.get("max_tokens", 2000))
        response = await super().complete(system, user, **kwargs)
        transport = "vertex" if self.transport == "vertex" else str(self.transport)
        self.ledger.record(response, f"claude/{transport}", _json_valid(response.content))
        return response


class RecordingGemini(GeminiClient):
    """GeminiClient with the same gate and recording."""

    def __init__(self, ledger: Ledger, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ledger = ledger

    async def complete(self, system: str, user: str, **kwargs: Any) -> LLMResponse:  # type: ignore[override]
        model = kwargs.get("model") or model_for(Role.GEMINI_DEFAULT)
        self.ledger.admit(model, len(system) + len(user), kwargs.get("max_tokens", 2000))
        response = await super().complete(system, user, **kwargs)
        self.ledger.record(response, _gemini_transport(), _json_valid(response.content))
        return response


def _gemini_transport() -> str:
    if os.environ.get("VERTEX_PROJECT"):
        return f"gemini/vertex:{os.environ.get('VERTEX_LOCATION', 'global')}"
    return "gemini/ai-studio"


# ------------------------------------------------------------------ probes

_JSON_TASK = (
    "Return ONLY a JSON object, no prose, with keys "
    '"summary" (one sentence, max 25 words) and "keywords" (exactly 3 strings).'
)
_SAMPLE = (
    "Source passage: The Aral Sea shrank by about 90% between 1960 and 2010 after its "
    "feeder rivers, the Amu Darya and Syr Darya, were diverted for cotton irrigation."
)


async def probe_editorial(ledger: Ledger, llm: LLMClient, label: str = "") -> None:
    deck = DeckSpec.model_validate_json(DECK_PATH.read_text(encoding="utf-8"))
    target = next(s for s in deck.slides if s.slide_type.value not in {"title_hero"})
    editorial = EditorialPass(llm=llm)
    for language in (Language.UZ, Language.RU, Language.KAA, Language.EN):
        ledger.current_probe = f"editorial regen ({language.value}){label}"
        ledger.current_role = Role.SLIDE_WRITER.value
        localized = deck.model_copy(
            update={
                "language": language,
                "interview": deck.interview.model_copy(update={"language": language}),
            }
        )
        before = len(ledger.rows)
        try:
            result = await editorial.regenerate_slide_content(localized, target.slide_id, claims=[])
            outcome = f"slide ok, findings={len(result.findings)}"
        except Exception as exc:
            outcome = f"FAILED: {type(exc).__name__}: {exc}"[:160]
        for row in ledger.rows[before:]:
            row.note = outcome


async def probe_claude_roles(ledger: Ledger, llm: LLMClient) -> None:
    probes = [
        (Role.SECTION_DRAFTER, 7_800),
        (Role.RESEARCH_INTERVIEW, 5_200),
        (Role.RESEARCH_INTERVIEW, 1_040),
        (Role.ARTICLE_OUTLINE, 5_200),
    ]
    for role, max_tokens in probes:
        ledger.current_probe = f"{role.value} json ({max_tokens})"
        ledger.current_role = role.value
        await llm.complete(
            system="You are a precise academic assistant. " + _JSON_TASK,
            user=_SAMPLE,
            model=model_for(role),
            max_tokens=max_tokens,
        )
    # The registered fallback must also accept its pinned thinking/effort pair.
    ledger.current_probe = "fallback claude-sonnet-5"
    ledger.current_role = "fallback"
    await llm.complete(
        system=_JSON_TASK,
        user=_SAMPLE,
        model=spec(model_for(Role.SLIDE_WRITER)).fallback or "",
        max_tokens=2_000,
    )


async def probe_haiku_roles(ledger: Ledger, llm: LLMClient) -> None:
    for role, max_tokens in (
        (Role.RESEARCH_INTERVIEW, 5_200),
        (Role.RESEARCH_INTERVIEW, 1_040),
        (Role.ARTICLE_OUTLINE, 5_200),
        (Role.CLAUDE_DEFAULT, 2_000),
    ):
        ledger.current_probe = f"{role.value} json ({max_tokens})"
        ledger.current_role = role.value
        await llm.complete(
            system="You are a precise academic assistant. " + _JSON_TASK,
            user=_SAMPLE,
            model=model_for(role),
            max_tokens=max_tokens,
        )


async def probe_gemini_roles(ledger: Ledger, gemini: GeminiClient) -> None:
    probes = [
        (Role.DECK_PLANNER, 12_000),
        (Role.CONTENT_CRITIC, 12_000),
        (Role.THESIS_CLASSIFIER, 8_000),
        (Role.DESIGN_DIRECTION, 8_000),
        (Role.CLAIM_EXTRACTION, 8_000),
        (Role.INTERACTIVE_CONTENT, 8_000),
        (Role.CITATION_VERIFICATION, 4_000),
    ]
    for role, max_tokens in probes:
        ledger.current_probe = f"{role.value} json ({max_tokens})"
        ledger.current_role = role.value
        await gemini.complete(
            system="You are a precise academic assistant. " + _JSON_TASK,
            user=_SAMPLE,
            model=model_for(role),
            max_tokens=max_tokens,
        )


async def probe_brain_tools(ledger: Ledger, gemini: GeminiClient) -> None:
    """DECK_BRAIN runs tool calls; one forced-ANY call proves the Pro tool path."""

    ledger.current_probe = "deck_brain tool call (ANY)"
    ledger.current_role = Role.DECK_BRAIN.value
    model = model_for(Role.DECK_BRAIN)
    ledger.admit(model, 400, 2_000)
    tool = genai_types.Tool(
        function_declarations=[
            genai_types.FunctionDeclaration(
                name="record_fact",
                description="Record one fact from the passage.",
                parameters_json_schema={
                    "type": "object",
                    "properties": {"fact": {"type": "string"}},
                    "required": ["fact"],
                },
            )
        ]
    )
    result = await gemini.generate_with_tools(
        contents=[genai_types.Content(role="user", parts=[genai_types.Part(text=_SAMPLE)])],
        tools=[tool],
        system="Record the single most important fact with the tool.",
        model=model,
        max_tokens=2_000,
        tool_mode=genai_types.FunctionCallingConfigMode.ANY,
    )
    ledger.spent += result.estimated_cost_usd
    ledger.rows.append(
        Row(
            ledger.current_probe,
            ledger.current_role,
            result.model,
            _gemini_transport(),
            result.latency_ms,
            result.input_tokens,
            result.output_tokens,
            -1,
            result.estimated_cost_usd,
            "yes (tool args)" if result.function_calls else "no tool call",
            "no" if result.function_calls else f"? ({result.finish_reason})",
            note=f"function_calls={len(result.function_calls)}",
        )
    )


async def probe_images(ledger: Ledger, images: GeminiImageClient) -> None:
    model = model_for(Role.IMAGE_GENERATION)
    ledger.current_probe = "image generation"
    ledger.current_role = Role.IMAGE_GENERATION.value
    cost = image_cost_usd(model)
    if ledger.spent + cost > ledger.cap:
        raise BudgetExceededError("image generation would cross the cap")
    start = time.perf_counter()
    image = await images.generate_image(
        "A flat, minimal illustration of a dried lakebed with a stranded fishing boat. No text."
    )
    latency = int((time.perf_counter() - start) * 1000)
    ledger.spent += cost
    ledger.rows.append(
        Row(
            ledger.current_probe,
            ledger.current_role,
            model,
            _gemini_transport(),
            latency,
            -1,
            -1,
            -1,
            cost,
            "n/a",
            "n/a",
            note=f"{image.content_type}, {len(image.data)} bytes",
        )
    )

    ledger.current_probe = "vision caption"
    ledger.current_role = Role.VISION_CAPTION.value
    vision = model_for(Role.VISION_CAPTION)
    ledger.admit(vision, 4_000, 300)
    start = time.perf_counter()
    caption = await images.caption_image(
        image.data, image.content_type, "Describe this image in one sentence."
    )
    latency = int((time.perf_counter() - start) * 1000)
    # The image client logs no token usage; price the worst case so the cap holds.
    worst = token_cost_usd(vision, 2_000, 300)
    ledger.spent += worst
    ledger.rows.append(
        Row(
            ledger.current_probe,
            ledger.current_role,
            vision,
            _gemini_transport(),
            latency,
            -1,
            -1,
            -1,
            worst,
            "n/a",
            "n/a",
            note=f"caption: {caption[:80]!r} (cost = upper bound)",
        )
    )


# ------------------------------------------------------------------ main


def _print_table(ledger: Ledger) -> None:
    header = (
        "| probe | role | model | transport | latency ms | in | out | thinking | cost $ "
        "| JSON valid | truncated | note |"
    )
    print(header)
    print("|" + "---|" * 12)
    for r in ledger.rows:
        cells = [
            r.probe,
            r.role,
            r.model,
            r.transport,
            str(r.latency_ms),
            str(r.input_tokens),
            str(r.output_tokens),
            str(r.thinking_tokens),
            f"{r.cost_usd:.5f}",
            r.json_valid,
            r.truncated,
            r.note.replace("|", "/"),
        ]
        print("| " + " | ".join(cells) + " |")
    print(f"\nTotal spend (registry prices): ${ledger.spent:.4f} of ${ledger.cap:.2f} cap")


async def run(mode: str) -> int:
    ledger = Ledger(HARD_CAP_USD)
    probes: list[tuple[str, Callable[[], Awaitable[None]]]]
    if mode == "haiku-only":
        haiku = model_for(Role.CLAUDE_DEFAULT)
        llm = RecordingLLM(ledger)
        stand_in = RecordingLLM(ledger, stand_in=haiku)
        probes = [
            ("editorial", lambda: probe_editorial(ledger, stand_in, " [Haiku stand-in]")),
            ("haiku roles", lambda: probe_haiku_roles(ledger, llm)),
        ]
    else:
        if mode == "dry-run":
            from scripts._smoke_b0_fakes import fake_clients

            llm, gemini, images = fake_clients(ledger)
        else:
            llm = RecordingLLM(ledger)
            gemini = RecordingGemini(ledger)
            images = GeminiImageClient()
            for role in (Role.DECK_PLANNER, Role.GEMINI_DEFAULT, Role.IMAGE_GENERATION):
                gemini_request_id(model_for(role))  # fail fast on a bad location
        probes = [
            ("editorial", lambda: probe_editorial(ledger, llm)),
            ("claude roles", lambda: probe_claude_roles(ledger, llm)),
            ("gemini roles", lambda: probe_gemini_roles(ledger, gemini)),
            ("brain tools", lambda: probe_brain_tools(ledger, gemini)),
            ("images", lambda: probe_images(ledger, images)),
        ]
    failures = 0
    for name, probe in probes:
        try:
            await probe()
        except BudgetExceededError as exc:
            print(f"STOP ({name}): {exc}")
            failures += 1
            break
        except Exception as exc:
            print(f"FAILED ({name}): {type(exc).__name__}: {exc}")
            failures += 1
    _print_table(ledger)
    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--spend", action="store_true", help="make REAL paid calls (cap $5)")
    mode.add_argument(
        "--haiku-only", action="store_true", help="REAL Haiku 5.5 calls over the Claude API"
    )
    args = parser.parse_args()
    if not args.dry_run:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    if args.haiku_only:
        # Transport is frozen when each LLMClient is built, so set it first.
        os.environ["LLM_TRANSPORT"] = "anthropic"
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    mode = "dry-run" if args.dry_run else "haiku-only" if args.haiku_only else "spend"
    raise SystemExit(asyncio.run(run(mode)))


if __name__ == "__main__":
    main()
