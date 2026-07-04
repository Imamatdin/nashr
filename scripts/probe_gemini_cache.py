"""Throwaway probe: does Gemini explicit context-caching accept the brain's tools?

MEASUREMENT ONLY. This script is deliberately NOT imported by any production code
and NOT collected by pytest (it lives outside ``testpaths=["tests"]`` and its name
does not match ``test_*``). It exists to answer one deferred (5b) question with a
live call instead of a guess: can an explicit ``cached_content`` be created over
the REAL brain system block + the ``edit_slides`` tool declaration on Gemini 3.1
Pro, and does a subsequent ``generate_content`` referencing that cache report a
non-zero ``cached_content_token_count``?

It does NOT wire caching into any production path — that is 5b scope and is
explicitly out of bounds here. It only creates a cache, makes ONE generation call
against it, prints the usage metadata, and deletes the cache.

The sequence:

  1. Assemble the real Way 2 system block (``assemble_brain_system``) and the
     ``edit_slides`` tool (``build_edit_slides_tool``).
  2. Create an explicit cache: ``client.aio.caches.create(model=..., config=
     CreateCachedContentConfig(system_instruction=..., tools=[...], ttl='300s',
     display_name='nashr-cache-probe'))``.
  3. ONE ``generate_content`` with ``GenerateContentConfig(cached_content=<name>)``
     and a trivial user turn; print prompt/candidates/cached token counts.
  4. Delete the cache in a ``finally``.

Every failure mode is a FINDING, not a crash: if the API rejects tools-in-a-cache
or ``cached_content`` on this model/endpoint, the error text is printed with a
diagnosis and the script exits 1 — a rejection is itself the measurement. It never
exits on a bare stack trace.

Companion measurement (IMPLICIT caching) — no explicit cache needed:
Gemini also caches repeated prefixes implicitly. To measure that, make two
back-to-back UNCACHED ``GeminiClient.generate_with_tools`` calls with the same
large system+tools prefix; the SECOND may return a non-zero
``cached_content_token_count``. That count is now observable without this probe
via CHANGE 1's ``cached_input_tokens`` field on the ``gemini_call_complete`` log
line (``packages/core/gemini.py``). This explicit-cache probe and that implicit
log signal are the two halves of the caching-observability picture.

Run from the repo root with live Vertex (or AI Studio) creds:

    set VERTEX_PROJECT=...        # Vertex AI + ADC (gcloud auth ... login)
    # or, for AI Studio instead of Vertex: set GOOGLE_API_KEY=...
    python scripts/probe_gemini_cache.py

Exit 0 iff the cache was created AND the cached generation succeeded; 1 on any
API rejection or unexpected error (with a printed diagnosis); 2 if creds missing.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import google.genai as genai  # noqa: E402
from google.genai import errors as genai_errors  # noqa: E402
from google.genai import types as genai_types  # noqa: E402

from packages.core.brain_loop import build_edit_slides_tool  # noqa: E402
from packages.core.brain_prompts import assemble_brain_system  # noqa: E402
from packages.core.gemini import (  # noqa: E402
    GEMINI_PRO_3_1_MODEL,
    build_default_genai_client,
)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional; env may be exported directly.
    pass


_CACHE_TTL = "300s"
_CACHE_DISPLAY_NAME = "nashr-cache-probe"
_USER_TURN = (
    "Acknowledge in one short sentence that you are ready to edit slides. Do not call any tool."
)


def _print_usage(usage: genai_types.GenerateContentResponseUsageMetadata | None) -> None:
    """Print the token counts a cached generation returns, defensively."""

    if usage is None:
        print("  usage_metadata is None (no token accounting returned).")
        return
    prompt = getattr(usage, "prompt_token_count", None)
    candidates = getattr(usage, "candidates_token_count", None)
    cached = getattr(usage, "cached_content_token_count", None)
    total = getattr(usage, "total_token_count", None)
    print(f"  prompt_token_count:         {prompt}")
    print(f"  candidates_token_count:     {candidates}")
    print(f"  cached_content_token_count: {cached}")
    print(f"  total_token_count:          {total}")
    print(f"  (full usage_metadata) {usage!r}")


async def _run_probe(client: genai.Client) -> int:
    """Create a cache, run one cached generation, print usage, delete the cache."""

    system = assemble_brain_system()
    tool = build_edit_slides_tool()
    print(f"Probe model:        {GEMINI_PRO_3_1_MODEL}")
    print(f"System block chars: {len(system)}")
    print(f"Requested TTL:      {_CACHE_TTL}")

    try:
        cache = await client.aio.caches.create(
            model=GEMINI_PRO_3_1_MODEL,
            config=genai_types.CreateCachedContentConfig(
                system_instruction=system,
                tools=[tool],
                ttl=_CACHE_TTL,
                display_name=_CACHE_DISPLAY_NAME,
            ),
        )
    except genai_errors.APIError as exc:
        print(
            "FINDING: explicit cache creation with system+tools was REJECTED — "
            f"{type(exc).__name__} code={getattr(exc, 'code', None)}: {exc}"
        )
        print(
            "Interpretation: an explicit cached_content over the brain's tool set may be "
            "unsupported on this model/endpoint. The implicit-caching path (CHANGE 1's "
            "cached_input_tokens on back-to-back generate_with_tools) stays the fallback signal."
        )
        return 1

    cache_name = cache.name
    if cache_name is None:
        print(
            "FINDING: cache was created but carries no .name; cannot reference it. Nothing to do."
        )
        return 1

    print(f"Cache created:      name={cache_name} display_name={cache.display_name}")
    print(f"Server expire_time: {cache.expire_time}")
    if cache.usage_metadata is not None:
        print(f"Cache usage_metadata: {cache.usage_metadata!r}")

    try:
        response = await client.aio.models.generate_content(
            model=GEMINI_PRO_3_1_MODEL,
            contents=[genai_types.Content(role="user", parts=[genai_types.Part(text=_USER_TURN)])],
            config=genai_types.GenerateContentConfig(cached_content=cache_name),
        )
        print("\nGenerate with cached_content SUCCEEDED. usage_metadata:")
        _print_usage(response.usage_metadata)
        print(
            "\nFINDING: explicit cached_content over the brain system+tools is SUPPORTED; the "
            "cached_content_token_count above is the prefix served from cache."
        )
        return 0
    except genai_errors.APIError as exc:
        print(
            "FINDING: generate_content with cached_content was REJECTED — "
            f"{type(exc).__name__} code={getattr(exc, 'code', None)}: {exc}"
        )
        return 1
    finally:
        try:
            await client.aio.caches.delete(name=cache_name)
            print(f"Cleanup: deleted cache {cache_name}.")
        except genai_errors.APIError as exc:
            print(f"Cleanup WARNING: could not delete cache {cache_name}: {exc}")


async def _amain() -> int:
    if not (
        os.environ.get("VERTEX_PROJECT")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
    ):
        print(
            "Set VERTEX_PROJECT (Vertex AI + ADC) — or GOOGLE_API_KEY / GEMINI_API_KEY for AI "
            "Studio. This probe creates a REAL Gemini 3.1 Pro context cache."
        )
        return 2

    client = build_default_genai_client()
    return await _run_probe(client)


def main() -> int:
    # A throwaway probe converts any unexpected failure into a printed finding and a
    # nonzero exit — never a raw stack trace (see the module docstring).
    try:
        return asyncio.run(_amain())
    except Exception as exc:
        print(f"PROBE ERRORED (unexpected): {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
