"""Provider-agnostic LLM router.

Routes :meth:`complete` calls to either :class:`packages.core.llm.LLMClient`
or :class:`packages.core.gemini.GeminiClient` based on the leading
identifier of the model name (``claude-*`` or ``gemini-*``). Both
clients return the same :class:`LLMResponse`, so consumers only need to
know which model they want — not which provider implements it.

Each provider client is constructed lazily on first use so that a
project which only calls Claude does not need ``GOOGLE_API_KEY`` set
(and vice versa).
"""

from __future__ import annotations

from packages.core.gemini import GeminiClient
from packages.core.llm import DEFAULT_HAIKU_MODEL, LLMClient, LLMResponse


class ModelRouter:
    """Dispatches one :meth:`complete` call to the matching provider.

    Holds at most one instance of each provider client and creates them
    lazily. Tests can pre-seed clients via the constructor to avoid
    triggering live SDK initialization.
    """

    def __init__(
        self,
        anthropic: LLMClient | None = None,
        gemini: GeminiClient | None = None,
    ) -> None:
        self._anthropic: LLMClient | None = anthropic
        self._gemini: GeminiClient | None = gemini

    def _get_anthropic(self) -> LLMClient:
        """Return (and lazily create) the Anthropic client."""

        if self._anthropic is None:
            self._anthropic = LLMClient()
        return self._anthropic

    def _get_gemini(self) -> GeminiClient:
        """Return (and lazily create) the Gemini client."""

        if self._gemini is None:
            self._gemini = GeminiClient()
        return self._gemini

    async def complete(
        self,
        system: str,
        user: str,
        model: str = DEFAULT_HAIKU_MODEL,
        max_tokens: int = 2000,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Route to the correct provider based on ``model``'s prefix.

        Raises :class:`ValueError` if the model is neither Claude nor
        Gemini — workers must never call this method with a model name
        from an unsupported provider.
        """

        if model.startswith("claude"):
            return await self._get_anthropic().complete(
                system=system,
                user=user,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        if model.startswith("gemini"):
            return await self._get_gemini().complete(
                system=system,
                user=user,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        raise ValueError(f"Unknown model provider for model: {model}")
