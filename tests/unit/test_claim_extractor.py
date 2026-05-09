"""Behaviour tests for :class:`ClaimExtractor`.

We mock :class:`LLMClient.complete` to return controlled responses so the
tests pin the parsing/validation behaviour exercised on each LLM reply
shape (well-formed JSON, malformed JSON, oversized claims, invalid
strength enums, etc.). The Anthropic call itself is covered separately
in ``test_llm_client.py``.

Per ``.claude/rules/testing.md`` we mock external LLM APIs but never
local libraries, so this file uses a minimal in-memory stub of the LLM
client rather than monkeypatching pydantic or anthropic internals.
"""

from __future__ import annotations

import json

import pytest

from packages.core.enums import ClaimStrength
from packages.core.llm import LLMResponse
from packages.core.models.source import SourceChunkCreate, SourceMetadataExtracted
from packages.workers.source.claim_extractor import (
    ClaimExtractor,
    _format_source_context,
)


class _StubLLM:
    """Stand-in for :class:`LLMClient` that returns scripted responses.

    ``responses`` is a list of strings consumed in order. When exhausted,
    raises ``RuntimeError`` so accidentally over-calling the LLM in a test
    fails loudly instead of silently returning ``""``.
    """

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        self.calls.append((system, user))
        if not self.responses:
            raise RuntimeError("LLM stub ran out of scripted responses")
        content = self.responses.pop(0)
        return LLMResponse(
            content=content,
            model=model,
            input_tokens=100,
            output_tokens=50,
            latency_ms=10,
            estimated_cost_usd=0.001,
        )


def _chunk(text: str = "Sample chunk text from a source.") -> SourceChunkCreate:
    return SourceChunkCreate(chunk_index=0, text=text, page=1)


def _metadata() -> SourceMetadataExtracted:
    return SourceMetadataExtracted(
        title="A History of Logic",
        authors=["Ali Karim", "Olga Petrova"],
        year=2019,
    )


def _valid_claims_payload() -> str:
    return json.dumps(
        [
            {
                "claim_text": "Logic emerged as a formal discipline in the 4th century BCE.",
                "quote": "Aristotle's Organon laid the foundations of formal logic.",
                "strength": "strong",
            },
            {
                "claim_text": "Stoic philosophers later extended propositional logic.",
                "quote": None,
                "strength": "moderate",
            },
        ]
    )


@pytest.mark.asyncio
async def test_extract_claims_parses_valid_json() -> None:
    stub = _StubLLM([_valid_claims_payload()])
    extractor = ClaimExtractor(llm=stub)  # type: ignore[arg-type]

    claims = await extractor.extract_claims_from_chunk(_chunk(), "ctx")

    assert len(claims) == 2
    assert claims[0].claim_text.startswith("Logic emerged")
    assert claims[0].strength == ClaimStrength.STRONG
    assert claims[1].quote is None


@pytest.mark.asyncio
async def test_extract_claims_handles_invalid_json() -> None:
    stub = _StubLLM(["Here are the claims: [invalid json", "still bad"])
    extractor = ClaimExtractor(llm=stub)  # type: ignore[arg-type]

    claims = await extractor.extract_claims_from_chunk(_chunk(), "ctx")

    assert claims == []
    assert len(stub.calls) == 2  # initial + one retry


@pytest.mark.asyncio
async def test_extract_claims_retries_on_bad_json_then_succeeds() -> None:
    stub = _StubLLM(["Here are the claims: not json", _valid_claims_payload()])
    extractor = ClaimExtractor(llm=stub)  # type: ignore[arg-type]

    claims = await extractor.extract_claims_from_chunk(_chunk(), "ctx")

    assert len(claims) == 2
    assert len(stub.calls) == 2


@pytest.mark.asyncio
async def test_extract_claims_filters_too_short_claims() -> None:
    payload = json.dumps(
        [
            {"claim_text": "tiny", "quote": None, "strength": "strong"},
            {
                "claim_text": "This claim is long enough to pass validation rules.",
                "quote": None,
                "strength": "strong",
            },
        ]
    )
    stub = _StubLLM([payload])
    extractor = ClaimExtractor(llm=stub)  # type: ignore[arg-type]

    claims = await extractor.extract_claims_from_chunk(_chunk(), "ctx")

    assert len(claims) == 1
    assert claims[0].claim_text.startswith("This claim is long enough")


@pytest.mark.asyncio
async def test_extract_claims_filters_too_long_claims() -> None:
    too_long = "x" * 600
    payload = json.dumps(
        [
            {"claim_text": too_long, "quote": None, "strength": "strong"},
            {
                "claim_text": "Another well-formed factual claim about the topic.",
                "quote": None,
                "strength": "moderate",
            },
        ]
    )
    stub = _StubLLM([payload])
    extractor = ClaimExtractor(llm=stub)  # type: ignore[arg-type]

    claims = await extractor.extract_claims_from_chunk(_chunk(), "ctx")

    assert len(claims) == 1
    assert claims[0].claim_text.startswith("Another well-formed")


@pytest.mark.asyncio
async def test_extract_claims_validates_strength_enum() -> None:
    payload = json.dumps(
        [
            {"claim_text": "First valid claim about a fact.", "quote": None, "strength": "strong"},
            {
                "claim_text": "Second valid claim about another.",
                "quote": None,
                "strength": "moderate",
            },
            {"claim_text": "Third valid claim, weakly stated.", "quote": None, "strength": "weak"},
        ]
    )
    stub = _StubLLM([payload])
    extractor = ClaimExtractor(llm=stub)  # type: ignore[arg-type]

    claims = await extractor.extract_claims_from_chunk(_chunk(), "ctx")

    assert [c.strength for c in claims] == [
        ClaimStrength.STRONG,
        ClaimStrength.MODERATE,
        ClaimStrength.WEAK,
    ]


@pytest.mark.asyncio
async def test_extract_claims_invalid_strength_skipped() -> None:
    payload = json.dumps(
        [
            {
                "claim_text": "Good claim with valid strength value.",
                "quote": None,
                "strength": "very_strong",
            },
            {
                "claim_text": "Other good claim with valid strength.",
                "quote": None,
                "strength": "strong",
            },
        ]
    )
    stub = _StubLLM([payload])
    extractor = ClaimExtractor(llm=stub)  # type: ignore[arg-type]

    claims = await extractor.extract_claims_from_chunk(_chunk(), "ctx")

    assert len(claims) == 1
    assert claims[0].strength == ClaimStrength.STRONG


def test_extract_claims_source_context_formatting_full() -> None:
    ctx = _format_source_context(_metadata())
    assert "A History of Logic" in ctx
    assert "Ali Karim" in ctx
    assert "Olga Petrova" in ctx
    assert "2019" in ctx


def test_extract_claims_source_context_formatting_sparse() -> None:
    ctx = _format_source_context(SourceMetadataExtracted())
    assert ctx == "Unknown source"


@pytest.mark.asyncio
async def test_extract_claims_concurrent_batching() -> None:
    payload = _valid_claims_payload()
    stub = _StubLLM([payload] * 10)
    extractor = ClaimExtractor(llm=stub)  # type: ignore[arg-type]
    chunks = [
        SourceChunkCreate(chunk_index=i, text=f"Chunk {i} text content here.", page=1)
        for i in range(10)
    ]

    claims = await extractor.extract_claims(chunks, _metadata())

    assert len(stub.calls) == 10
    assert len(claims) == 20  # 2 claims per stubbed payload
