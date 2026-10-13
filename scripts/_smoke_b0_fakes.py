"""Offline clients for ``smoke_b0_models.py --dry-run``: real SDK response types, no network."""

from __future__ import annotations

from typing import Any

from anthropic.types import Message, TextBlock, Usage
from google.genai import types as genai_types

from packages.core.gemini_image import GeminiImageClient, GeneratedImage
from scripts.smoke_b0_models import Ledger, RecordingGemini, RecordingLLM

_JSON = '{"summary": "The Aral Sea shrank about 90% after river diversion.", "keywords": ["Aral", "irrigation", "cotton"]}'


class _Messages:
    async def create(self, **kwargs: Any) -> Message:
        usage = Usage.model_validate(
            {
                "input_tokens": 1_200,
                "output_tokens": 180,
                "output_tokens_details": {"thinking_tokens": 0},
            }
        )
        return Message(
            id="msg_dry",
            type="message",
            role="assistant",
            model=kwargs["model"],
            content=[TextBlock(type="text", text=_JSON, citations=None)],
            stop_reason="end_turn",
            stop_sequence=None,
            usage=usage,
        )


class _Anthropic:
    def __init__(self) -> None:
        self.messages = _Messages()


def _usage() -> genai_types.GenerateContentResponseUsageMetadata:
    return genai_types.GenerateContentResponseUsageMetadata(
        prompt_token_count=300, candidates_token_count=60, thoughts_token_count=120
    )


async def _generate(
    *, model: str, contents: Any, config: Any
) -> genai_types.GenerateContentResponse:
    del model, contents
    tools = getattr(config, "tools", None)
    part = (
        genai_types.Part(
            function_call=genai_types.FunctionCall(name="record_fact", args={"fact": "x"})
        )
        if tools
        else genai_types.Part(text=_JSON)
    )
    return genai_types.GenerateContentResponse(
        candidates=[
            genai_types.Candidate(
                content=genai_types.Content(role="model", parts=[part]),
                finish_reason=genai_types.FinishReason.STOP,
            )
        ],
        usage_metadata=_usage(),
    )


async def _image(*, model: str, prompt: str) -> GeneratedImage:
    del model, prompt
    return GeneratedImage(data=b"\x89PNG\r\n\x1a\nfake", content_type="image/png")


async def _caption(*, model: str, data: bytes, mime_type: str, instruction: str) -> str:
    del model, data, mime_type, instruction
    return "A dry lakebed with a stranded boat."


def fake_clients(ledger: Ledger) -> tuple[RecordingLLM, RecordingGemini, GeminiImageClient]:
    """Recording clients wired to offline fakes."""

    llm = RecordingLLM(ledger, client=_Anthropic())  # type: ignore[arg-type]
    gemini = RecordingGemini(ledger, generate_content_fn=_generate)
    images = GeminiImageClient(generate_image_fn=_image, caption_fn=_caption)
    return llm, gemini, images
