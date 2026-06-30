"""Split (de)serialization of ``SourceProcessingResult`` for the session store.

The fix tool re-grounds against a live ``SourceProcessingResult``, so the session
must persist it losslessly. Its only non-JSON field is ``figures[].data`` (raw
raster bytes), now base64 in jsonb via the model's ``ser/val_json_bytes`` config.

The bytes are heavy and rarely needed (most chat turns are text-only), so they
are stored in their OWN column. :func:`serialize_sources` returns the light text
half and the heavy figure half separately; :func:`deserialize_sources` reattaches
them. A light per-turn load passes ``figures_json=None`` and gets a figure-less
result the chat loop hydrates only when a fix fires.
"""

from __future__ import annotations

from typing import Any

from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult


def serialize_sources(
    sources: SourceProcessingResult,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Serialize to (light text jsonb, heavy figures jsonb) for two columns.

    The light half is the full model minus ``figures``; the heavy half is the
    figure list dumped on its own (base64 bytes). Both go through
    ``model_dump(mode="json")`` so the round-trip is lossless.
    """

    light = sources.model_dump(mode="json", exclude={"figures"})
    figures = [figure.model_dump(mode="json") for figure in sources.figures]
    return light, figures


def deserialize_sources(
    light_json: dict[str, Any],
    figures_json: list[dict[str, Any]] | None,
) -> SourceProcessingResult:
    """Reconstruct the result, reattaching figures when the heavy half is loaded.

    ``figures_json=None`` is the light per-turn load: the result comes back with
    an empty figure roster (the caller hydrates it before grounding a fix). A
    provided list is decoded back to ``SourceFigure`` objects with byte-exact
    ``data`` — ``model_validate`` applies the model's base64 ``val_json_bytes``
    to the nested figure payloads (the path Step 0 proved round-trips).
    """

    return SourceProcessingResult.model_validate({**light_json, "figures": figures_json or []})
