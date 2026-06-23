"""Async Gemini client for the image modality: generation + figure captioning.

The text :class:`packages.core.gemini.GeminiClient` returns text and cannot
produce or read images, so the image engine needs this sibling. It follows the
*same* contract — an injectable async fn per operation (so tests never touch the
SDK), a 30s timeout, up to two retries with exponential backoff, auth errors
propagating immediately, one info log per call — and reuses
:func:`packages.core.gemini.build_default_genai_client` for Vertex/AI-Studio
credentials. It is the established pattern extended to a new modality, not a new
client stack.

The generation model id is read from ``NASHR_IMAGE_MODEL`` so the deployed Vertex
model (Imagen / "Nano Banana") can change without a code edit; captioning uses
the multimodal flash text model. Generated images depict objects/concepts/scenes
only — never a real identifiable person (those are sourced from Commons).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar, Final, cast

from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import BaseModel, ConfigDict, Field

from packages.core.constants import DEFAULT_LLM_MAX_RETRIES, DEFAULT_LLM_TIMEOUT_SECONDS
from packages.core.gemini import GEMINI_FLASH_3_5_MODEL, build_default_genai_client

logger = logging.getLogger(__name__)

# Vision/captioning runs on the current-generation multimodal flash text model;
# image generation uses a dedicated image model whose id is deployment-configurable.
GEMINI_VISION_MODEL: Final[str] = GEMINI_FLASH_3_5_MODEL
DEFAULT_IMAGE_MODEL: Final[str] = os.environ.get("NASHR_IMAGE_MODEL", "gemini-3-pro-image")

# Flat per-image cost estimate for logging only (not billing). Carried over from
# the prior image model; revisit against gemini-3-pro-image's published price.
IMAGE_COST_USD: Final[float] = 0.039

# HTTP status codes that must not retry — a bad key is a config fault.
_AUTH_HTTP_CODES: Final[frozenset[int]] = frozenset({401, 403})

_CAPTION_MAX_TOKENS: Final[int] = 300


class GeneratedImage(BaseModel):
    """Raw bytes + content type of one generated image."""

    model_config = ConfigDict(extra="forbid")

    data: bytes
    content_type: str = Field(min_length=1, max_length=100)


GenerateImageFn = Callable[..., Awaitable[GeneratedImage]]
CaptionFn = Callable[..., Awaitable[str]]


class GeminiImageClient:
    """Async wrapper for Gemini image generation and figure captioning.

    Both operations are injectable fns; tests supply stubs and never construct a
    live :class:`google.genai.Client`. When either fn is omitted the default
    binds the shared SDK client (Vertex AI, else AI Studio).
    """

    DEFAULT_IMAGE_MODEL: ClassVar[str] = DEFAULT_IMAGE_MODEL
    VISION_MODEL: ClassVar[str] = GEMINI_VISION_MODEL

    def __init__(
        self,
        generate_image_fn: GenerateImageFn | None = None,
        caption_fn: CaptionFn | None = None,
        timeout_seconds: int = DEFAULT_LLM_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    ) -> None:
        if generate_image_fn is None or caption_fn is None:
            client = build_default_genai_client()
            self._generate_image_fn: GenerateImageFn = (
                generate_image_fn
                if generate_image_fn is not None
                else _default_generate_image_fn(client)
            )
            self._caption_fn: CaptionFn = (
                caption_fn if caption_fn is not None else _default_caption_fn(client)
            )
        else:
            self._generate_image_fn = generate_image_fn
            self._caption_fn = caption_fn
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    async def generate_image(
        self, prompt: str, *, model: str = DEFAULT_IMAGE_MODEL
    ) -> GeneratedImage:
        """Generate one image from ``prompt`` with retry, timeout, and cost logging."""

        start = time.perf_counter()
        result = await self._run_with_retry(
            "gemini_generate_image", lambda: self._generate_image_fn(model=model, prompt=prompt)
        )
        logger.info(
            "gemini_image_generated",
            extra={
                "model": model,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "estimated_cost_usd": IMAGE_COST_USD,
            },
        )
        return result

    async def caption_image(
        self,
        data: bytes,
        mime_type: str,
        instruction: str,
        *,
        model: str = GEMINI_VISION_MODEL,
    ) -> str:
        """Caption/understand an image (vision) with retry and timeout."""

        start = time.perf_counter()
        text = await self._run_with_retry(
            "gemini_caption_image",
            lambda: self._caption_fn(
                model=model, data=data, mime_type=mime_type, instruction=instruction
            ),
        )
        logger.info(
            "gemini_image_captioned",
            extra={"model": model, "latency_ms": int((time.perf_counter() - start) * 1000)},
        )
        return text

    async def _run_with_retry(self, op_name: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        """Run ``factory()`` with the shared timeout/backoff/auth policy.

        ``factory`` must mint a fresh awaitable per attempt. Auth errors (401/403)
        propagate without retry; transient API errors and timeouts back off.
        """

        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            try:
                return await asyncio.wait_for(factory(), timeout=self._timeout_seconds)
            except TimeoutError as exc:
                last_error = exc
            except genai_errors.APIError as exc:
                if exc.code in _AUTH_HTTP_CODES:
                    raise
                last_error = exc
            attempt += 1
            if attempt > self._max_retries:
                break
            backoff = 2 ** (attempt - 1)
            logger.warning(
                "gemini_image_call_retrying",
                extra={"op": op_name, "attempt": attempt, "backoff_seconds": backoff},
            )
            await asyncio.sleep(backoff)
        assert last_error is not None
        raise last_error


# ---------------------------------------------------------------------------
# Default SDK-bound fns (exercised only by the gated live tests)
# ---------------------------------------------------------------------------


def _default_caption_fn(client: Any) -> CaptionFn:
    """Bind a real google-genai client into the captioning fn shape."""

    async def fn(*, model: str, data: bytes, mime_type: str, instruction: str) -> str:
        response = await client.aio.models.generate_content(
            model=model,
            contents=[
                genai_types.Part.from_bytes(data=data, mime_type=mime_type),
                instruction,
            ],
            config=genai_types.GenerateContentConfig(
                max_output_tokens=_CAPTION_MAX_TOKENS, temperature=0.0
            ),
        )
        text = getattr(response, "text", None)
        return text if isinstance(text, str) else ""

    return fn


def _default_generate_image_fn(client: Any) -> GenerateImageFn:
    """Bind a real google-genai client into the image-generation fn shape."""

    async def fn(*, model: str, prompt: str) -> GeneratedImage:
        response = await client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=genai_types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        return _extract_generated_image(response)

    return fn


def _extract_generated_image(response: object) -> GeneratedImage:
    """Pull the first inline image part from a generate_content response."""

    candidates = getattr(response, "candidates", None)
    if isinstance(candidates, list):
        for candidate in cast("list[object]", candidates):
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None)
            if not isinstance(parts, list):
                continue
            for part in cast("list[object]", parts):
                inline = getattr(part, "inline_data", None)
                blob = getattr(inline, "data", None)
                mime = getattr(inline, "mime_type", None)
                if isinstance(blob, bytes) and isinstance(mime, str) and mime.startswith("image/"):
                    return GeneratedImage(data=blob, content_type=mime)
    raise RuntimeError("image generation returned no image part")


__all__ = [
    "DEFAULT_IMAGE_MODEL",
    "GEMINI_VISION_MODEL",
    "GeminiImageClient",
    "GeneratedImage",
]
