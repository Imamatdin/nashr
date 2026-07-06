"""Live probe: editorial-shaped Claude call through AnthropicVertex + cache read.

Run inside the bot container (ADC / vertex-key.json present):

    docker exec -e PYTHONPATH=/app -w /app nashr-bot python scripts/probe_vertex_claude_llm.py

Requires ``LLM_TRANSPORT=vertex`` (default) and ``VERTEX_PROJECT=nashr-prod``.
Reports whether the second cached call shows ``cache_read_input_tokens > 0``.
Cost appears in GCP billing (Vertex partner models), not the Anthropic console.

Quota reference (Sonnet 4.6, global endpoint, GA 2026-02): QPM 1500;
input TPM 1.5M (uncached + cache write); output TPM 150K. Editorial regen
fires several sequential Sonnet calls — within burst for one job; raise a
quota bump if parallel generation jobs saturate QPM.
"""

from __future__ import annotations

import asyncio
import os
import sys

from packages.core.llm import (
    DEFAULT_VERTEX_SONNET_MODEL,
    LLMClient,
    build_default_anthropic_client,
    resolve_llm_transport,
)

# Editorial-shaped prefix. Anthropic prompt caching has a MINIMUM cacheable prefix
# (1,024 tokens for Sonnet-class models); a shorter cache-marked prompt is silently
# processed WITHOUT caching — no error, cache_read stays 0 — which would false-FAIL
# this probe. The base rules are padded deterministically past that floor (~2k tokens).
_BASE_RULES = (
    "You are the editorial executor for an academic presentation engine. "
    "Return ONLY valid JSON matching the SlideContent schema. "
    "Every claim must be grounded in the supplied source claims. "
    "Never fabricate statistics, names, or citations. "
    "Preserve slide_type and structural fields unless instructed otherwise. "
)
_PADDING_RULES = "".join(
    f"Rule {i:02d}: ground every statistic, unit, and comparison in the supplied source "
    "claims; never invent values, journal names, page numbers, author initials, dates, "
    "URLs, or affiliations; prefer omission over fabrication whenever a detail is not "
    "verbatim in the sources; keep titles under the declared word limits. "
    for i in range(1, 41)
)
_SYSTEM = _BASE_RULES + _PADDING_RULES
_USER = (
    "Draft one slide titled 'Probe slide' with two bullets grounded in: "
    "'The proposed sCO2 cooling framework achieves a PUE of 1.08.'"
)


async def main() -> None:
    transport = resolve_llm_transport()
    if transport != "vertex":
        print(f"LLM_TRANSPORT={transport!r} — set LLM_TRANSPORT=vertex for this probe.")
        sys.exit(1)
    project = os.environ.get("VERTEX_PROJECT", "(unset)")
    region = os.environ.get("VERTEX_CLAUDE_REGION") or os.environ.get("VERTEX_LOCATION") or "global"
    print(f"transport=vertex project={project} region={region} model={DEFAULT_VERTEX_SONNET_MODEL}")
    client = LLMClient()
    assert client.transport == "vertex"
    print(f"client_transport={client.transport}")

    first = await client.complete(
        system=_SYSTEM,
        user=_USER,
        model=DEFAULT_VERTEX_SONNET_MODEL,
        max_tokens=512,
        temperature=0.0,
        cache="5m",
    )
    second = await client.complete(
        system=_SYSTEM,
        user=_USER + " (repeat)",
        model=DEFAULT_VERTEX_SONNET_MODEL,
        max_tokens=512,
        temperature=0.0,
        cache="5m",
    )

    print("\n--- call 1 (cache write expected) ---")
    print(f"ok content_len={len(first.content)} cost=${first.estimated_cost_usd:.6f}")
    print(
        f"tokens in={first.input_tokens} out={first.output_tokens} "
        f"cache_read={first.cache_read_input_tokens} cache_write={first.cache_creation_input_tokens}"
    )
    print("\n--- call 2 (cache read expected) ---")
    print(f"ok content_len={len(second.content)} cost=${second.estimated_cost_usd:.6f}")
    print(
        f"tokens in={second.input_tokens} out={second.output_tokens} "
        f"cache_read={second.cache_read_input_tokens} cache_write={second.cache_creation_input_tokens}"
    )

    if second.cache_read_input_tokens <= 0:
        print(
            "\nFAIL: second call shows cache_read_input_tokens=0 — "
            "Vertex Claude caching may differ from direct API; do NOT ship silently."
        )
        sys.exit(2)

    if second.estimated_cost_usd >= first.estimated_cost_usd:
        print(
            "\nWARN: second call not cheaper than first — verify cache-read pricing in GCP billing."
        )
    else:
        print("\nPASS: cache read observed; second call cheaper on estimated_cost_usd.")

    # Construction smoke — fallback path env-gated, not exercised here.
    _ = build_default_anthropic_client()


if __name__ == "__main__":
    asyncio.run(main())
