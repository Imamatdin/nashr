"""The image stage: resolve every image slot in a deck, in parallel, or abstain.

Runs after the Editorial Pass and before render. It walks the deck and, for each
unfilled image slot, resolves an image and writes the ``_url``:

* person portraits (``PersonItem``) and timeline portraits (``TimelineNode``)
  → gated Wikimedia Commons sourcing (:mod:`packages.presentation.commons_portraits`);
* contained object/concept figures (``figure_prompt``) and the title-hero scene
  background → source-informed generation
  (:mod:`packages.presentation.image_generation`).

Every slot resolves CONCURRENTLY (:func:`asyncio.gather`), each resolved image is
re-hosted via :class:`FileStorage` under ``temp/{project_id}/`` and its retrievable
URL written back to the slot. Any failure or low-confidence result abstains —
the ``_url`` stays ``None`` and the deck renders that slide exactly as before. The
stage never raises into the pipeline and never writes a junk url.

Generated images (figures + the hero background) consume a per-deck budget;
Commons portraits are free of that budget. The budget arrives PER CALL on
:meth:`ImagePass.resolve_deck` (``max_generated_images=…``) so it can be
derived from the user's :class:`GenerationPackage` for that job — see
``image_budget_for_package`` in :mod:`packages.core.constants` and the
orchestrator's ``resolve_images``. The constructor still accepts a default
budget so unit tests and ad-hoc callers can construct an ``ImagePass``
without specifying it, but production always passes it per-call (invariant
I1, ``docs/INVARIANTS.md``: no constant standing in for tier logic).

Within the budget, the title-hero scene background takes the FIRST claim
(invariant I3) — it is the highest-leverage image in any deck, and starving
it for a contained figure leaves the opening slide naked. Figures consume
the remainder. A zero budget (basic tier) generates nothing, hero included.

CC-BY portraits carry attribution, which is folded into the affected slide's
``speaker_notes`` — there is no separate credits slide (PD/CC0 need no credit).
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from uuid import uuid4

import httpx

from packages.core.enums import ImageSubjectType, SlideType
from packages.core.models.presentation import (
    DeckSpec,
    DesignDirectionSpec,
    PersonItem,
    SlideSpec,
    TimelineNode,
)
from packages.core.models.source import SourceFigure
from packages.platform.storage import FileStorage
from packages.presentation.commons_portraits import CommonsPortraitResolver
from packages.presentation.image_generation import GeneratedImageResolver
from packages.presentation.image_types import ImageAttribution, ResolvedImage

logger = logging.getLogger(__name__)

# SPEC §8 tiers: basic=0, standard=2, premium=5 generated images per deck. This
# constructor-time default is the floor that lets a bare ``ImagePass()`` work in
# tests; production callers always pass a per-call budget derived from the
# user's GenerationPackage (invariant I1, docs/INVARIANTS.md). Commons portraits
# are real-likeness sourcing, not generation, and do NOT count against the budget.
DEFAULT_MAX_GENERATED_IMAGES: Final[int] = 2
_HTTP_TIMEOUT_SECONDS: Final[int] = 15
_SIGNED_URL_TTL_SECONDS: Final[int] = 7 * 24 * 3600  # 7 days; render happens at once
_MAX_SPEAKER_NOTES: Final[int] = 2000

# Within the generated-image budget, the title-hero scene takes the FIRST
# claim — the single highest-leverage image in a deck; starving it for a
# contained figure leaves the opening naked (invariant I3). Lower priority
# sorts earlier in the budgeted slice, so background (0) outranks figure (1).
_BACKGROUND_PRIORITY: Final[int] = 0  # title-hero scene → guaranteed first slot
_FIGURE_PRIORITY: Final[int] = 1  # contained object/concept → claims the remainder


@dataclass
class _ImageTask:
    """One image slot: how to resolve it and where to write the result."""

    slide: SlideSpec
    priority: int  # generated-image budget order; portraits use _PORTRAIT_PRIORITY
    run: Callable[[httpx.AsyncClient], Awaitable[ResolvedImage | None]]
    apply: Callable[[str], None]


_PORTRAIT_PRIORITY: Final[int] = -1  # not budgeted


def _default_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)


class ImagePass:
    """Resolve all of a deck's image slots in parallel; abstain on any failure."""

    def __init__(
        self,
        *,
        portrait_resolver: CommonsPortraitResolver | None = None,
        generated_resolver: GeneratedImageResolver | None = None,
        max_generated_images: int = DEFAULT_MAX_GENERATED_IMAGES,
        http_client_factory: Callable[[], httpx.AsyncClient] | None = None,
        signed_url_ttl: int = _SIGNED_URL_TTL_SECONDS,
    ) -> None:
        self._portraits = (
            portrait_resolver if portrait_resolver is not None else CommonsPortraitResolver()
        )
        self._generated = (
            generated_resolver if generated_resolver is not None else GeneratedImageResolver()
        )
        self._max_generated = max(0, max_generated_images)
        self._http_client_factory = (
            http_client_factory if http_client_factory is not None else _default_http_client
        )
        self._signed_url_ttl = signed_url_ttl

    async def resolve_deck(
        self,
        deck: DeckSpec,
        *,
        storage: FileStorage,
        project_id: str,
        figures: list[SourceFigure],
        max_generated_images: int | None = None,
    ) -> DeckSpec:
        """Resolve every unfilled image slot in ``deck`` and write its ``_url``.

        ``max_generated_images`` overrides the constructor default for this one
        call — the orchestrator passes the tier-derived budget so the budget is
        a property of the job, not of the engine instance (invariant I1). A
        ``None`` value falls back to the instance default, preserving the
        single-construction-then-many-calls pattern used by callers that have
        no tier (tests, ad-hoc tools). Returns the same (mutated) deck.
        """

        budget = (
            self._max_generated if max_generated_images is None else max(0, max_generated_images)
        )
        portrait_tasks, generate_tasks = self._collect(deck, figures)
        # Sort ascending by priority so the title-hero background (0) wins the
        # first slot, then figures (1) consume the remainder up to the budget
        # — invariant I3: highest-leverage image is never starved by lower-
        # priority images within a non-zero budget.
        generate_tasks.sort(key=lambda t: t.priority)
        budgeted_generates = generate_tasks[:budget]
        tasks = portrait_tasks + budgeted_generates
        if not tasks:
            return deck

        # Resolve, re-host, and write back every slot CONCURRENTLY — both the
        # network resolution and the upload are I/O-bound, so the whole stage
        # is one gather, not a serial loop.
        client = self._http_client_factory()
        try:
            await asyncio.gather(
                *(self._process_task(task, client, storage, project_id) for task in tasks)
            )
        finally:
            await client.aclose()
        return deck

    async def _process_task(
        self,
        task: _ImageTask,
        client: httpx.AsyncClient,
        storage: FileStorage,
        project_id: str,
    ) -> None:
        """Resolve one slot, re-host it, and write its url — abstain on any error.

        Wrapped so a single slot's failure never propagates out of the gather and
        never crashes the deck; it just leaves that slot's ``_url`` null.
        """

        try:
            result = await task.run(client)
            if result is None:
                return
            url = await self._store(storage, project_id, result)
            if url is None:
                return
            task.apply(url)
            if result.attribution is not None:
                _append_attribution(task.slide, result.attribution)
        except Exception as exc:
            logger.warning("image_task_failed", extra={"error_type": type(exc).__name__})

    # ------------------------------------------------------------ task building

    def _collect(
        self, deck: DeckSpec, figures: list[SourceFigure]
    ) -> tuple[list[_ImageTask], list[_ImageTask]]:
        """Walk the deck and build one task per unfilled image slot."""

        design = deck.design
        portraits: list[_ImageTask] = []
        generates: list[_ImageTask] = []

        for slide in deck.slides:
            content = slide.content
            for person in content.people or []:
                if person.portrait_url is None and person.name:
                    portraits.append(self._person_task(slide, person))
            for node in content.timeline_nodes or []:
                if node.portrait_url is None and node.portrait_prompt:
                    portraits.append(self._timeline_task(slide, node))
            if content.figure_prompt and content.figure_url is None:
                generates.append(self._figure_task(slide, design, figures))
            if slide.slide_type is SlideType.TITLE_HERO and content.background_url is None:
                generates.append(self._background_task(slide, deck, figures))

        return portraits, generates

    def _person_task(self, slide: SlideSpec, person: PersonItem) -> _ImageTask:
        async def run(client: httpx.AsyncClient) -> ResolvedImage | None:
            return await self._portraits.resolve(
                client,
                person.name,
                years=person.years,
                role=person.role,
                description=person.description,
            )

        def apply(url: str) -> None:
            person.portrait_url = url

        return _ImageTask(slide=slide, priority=_PORTRAIT_PRIORITY, run=run, apply=apply)

    def _timeline_task(self, slide: SlideSpec, node: TimelineNode) -> _ImageTask:
        name = node.portrait_prompt or ""

        async def run(client: httpx.AsyncClient) -> ResolvedImage | None:
            return await self._portraits.resolve(client, name, description=node.label)

        def apply(url: str) -> None:
            node.portrait_url = url

        return _ImageTask(slide=slide, priority=_PORTRAIT_PRIORITY, run=run, apply=apply)

    def _figure_task(
        self, slide: SlideSpec, design: DesignDirectionSpec, figures: list[SourceFigure]
    ) -> _ImageTask:
        prompt = slide.content.figure_prompt or ""
        subject_type = slide.content.figure_subject_type or ImageSubjectType.OBJECT

        async def run(_client: httpx.AsyncClient) -> ResolvedImage | None:
            return await self._generated.resolve(prompt, subject_type, design, figures)

        def apply(url: str) -> None:
            slide.content.figure_url = url

        return _ImageTask(slide=slide, priority=_FIGURE_PRIORITY, run=run, apply=apply)

    def _background_task(
        self, slide: SlideSpec, deck: DeckSpec, figures: list[SourceFigure]
    ) -> _ImageTask:
        subject = ", ".join(p for p in (deck.title, deck.subtitle) if p)

        async def run(_client: httpx.AsyncClient) -> ResolvedImage | None:
            return await self._generated.resolve(
                subject, ImageSubjectType.SCENE, deck.design, figures
            )

        def apply(url: str) -> None:
            slide.content.background_url = url

        return _ImageTask(slide=slide, priority=_BACKGROUND_PRIORITY, run=run, apply=apply)

    # ----------------------------------------------------------------- storage

    async def _store(
        self, storage: FileStorage, project_id: str, image: ResolvedImage
    ) -> str | None:
        """Re-host one image under ``temp/{project_id}/`` and return its URL.

        The bytes are written to a scoped temp dir, uploaded via FileStorage, and
        a (7-day) signed URL returned as the retrievable reference. Any failure
        returns ``None`` so the slot abstains rather than carrying a junk url.
        """

        key = f"temp/{project_id}/{uuid4().hex}{image.extension}"
        try:
            with tempfile.TemporaryDirectory(prefix="nashr_img_") as tmp:
                path = Path(tmp) / f"image{image.extension}"
                await asyncio.to_thread(path.write_bytes, image.data)
                await storage.upload(path, key, content_type=image.content_type)
            return await storage.signed_url(key, expires_in=self._signed_url_ttl)
        except Exception as exc:
            logger.warning("image_store_failed", extra={"error_type": type(exc).__name__})
            return None


def _append_attribution(slide: SlideSpec, attribution: ImageAttribution) -> None:
    """Fold a CC-BY attribution line into the slide's speaker notes (capped)."""

    note = attribution.to_note()
    existing = (slide.content.speaker_notes or "").strip()
    combined = f"{existing}\n\n{note}".strip() if existing else note
    slide.content.speaker_notes = combined[:_MAX_SPEAKER_NOTES]


__all__ = ["DEFAULT_MAX_GENERATED_IMAGES", "ImagePass"]
