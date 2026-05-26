"""Behaviour tests for :class:`GeminiImageClient` (image gen + vision caption).

The SDK calls are injected as stub fns, so these never touch google-genai or the
network (per ``.claude/rules/testing.md``: external LLM APIs may be mocked).
Retry/backoff is exercised with ``asyncio.sleep`` patched to run instantly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from google.genai import errors as genai_errors

from packages.core.gemini_image import GeminiImageClient, GeneratedImage, _extract_generated_image


def _rate_limited() -> genai_errors.ServerError:
    return genai_errors.ServerError(503, {"error": {"status": "UNAVAILABLE", "message": "busy"}})


def _permission_denied() -> genai_errors.ClientError:
    return genai_errors.ClientError(403, {"error": {"status": "PERMISSION_DENIED", "message": "x"}})


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("packages.core.gemini_image.asyncio.sleep", _instant)


@pytest.mark.asyncio
async def test_generate_image_returns_bytes() -> None:
    async def gen(*, model: str, prompt: str) -> GeneratedImage:
        assert "server rack" in prompt
        return GeneratedImage(data=b"PNGDATA", content_type="image/png")

    client = GeminiImageClient(generate_image_fn=gen, caption_fn=_unused_caption())
    result = await client.generate_image("a server rack")
    assert result.data == b"PNGDATA"
    assert result.content_type == "image/png"


@pytest.mark.asyncio
async def test_caption_image_returns_text() -> None:
    async def cap(*, model: str, data: bytes, mime_type: str, instruction: str) -> str:
        assert data == b"IMG"
        assert mime_type == "image/jpeg"
        return "a 42U server rack with liquid cooling"

    client = GeminiImageClient(generate_image_fn=_unused_gen(), caption_fn=cap)
    text = await client.caption_image(b"IMG", "image/jpeg", "describe")
    assert "42U server rack" in text


@pytest.mark.asyncio
async def test_generate_image_retries_then_succeeds() -> None:
    attempts = {"n": 0}

    async def gen(*, model: str, prompt: str) -> GeneratedImage:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _rate_limited()
        return GeneratedImage(data=b"OK", content_type="image/png")

    client = GeminiImageClient(generate_image_fn=gen, caption_fn=_unused_caption())
    result = await client.generate_image("retry me")
    assert result.data == b"OK"
    assert attempts["n"] == 2


@pytest.mark.asyncio
async def test_auth_error_does_not_retry() -> None:
    attempts = {"n": 0}

    async def gen(*, model: str, prompt: str) -> GeneratedImage:
        attempts["n"] += 1
        raise _permission_denied()

    client = GeminiImageClient(generate_image_fn=gen, caption_fn=_unused_caption())
    with pytest.raises(genai_errors.ClientError):
        await client.generate_image("nope")
    assert attempts["n"] == 1  # auth failures are not retried


# ---------------------------------------------------------------------------
# Response extraction (the default SDK fn's parser)
# ---------------------------------------------------------------------------


class _FakeInline:
    def __init__(self, data: bytes, mime_type: str) -> None:
        self.data = data
        self.mime_type = mime_type


class _FakePart:
    def __init__(self, inline_data: object) -> None:
        self.inline_data = inline_data


class _FakeContent:
    def __init__(self, parts: list[object]) -> None:
        self.parts = parts


class _FakeCandidate:
    def __init__(self, parts: list[object]) -> None:
        self.content = _FakeContent(parts)


class _FakeResponse:
    def __init__(self, candidates: list[object]) -> None:
        self.candidates = candidates


def test_extract_generated_image_finds_inline_part() -> None:
    response = _FakeResponse([_FakeCandidate([_FakePart(_FakeInline(b"BYTES", "image/png"))])])
    result = _extract_generated_image(response)
    assert result.data == b"BYTES"
    assert result.content_type == "image/png"


def test_extract_generated_image_raises_when_no_image_part() -> None:
    response = _FakeResponse([_FakeCandidate([_FakePart(None)])])
    with pytest.raises(RuntimeError):
        _extract_generated_image(response)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _unused_gen() -> Callable[..., Awaitable[GeneratedImage]]:
    async def fn(*, model: str, prompt: str) -> GeneratedImage:  # pragma: no cover - not called
        raise AssertionError("generate should not be called")

    return fn


def _unused_caption() -> Callable[..., Awaitable[str]]:
    async def fn(*, model: str, data: bytes, mime_type: str, instruction: str) -> str:
        raise AssertionError("caption should not be called")  # pragma: no cover

    return fn


def _ignore(_: Any) -> None:
    return None
