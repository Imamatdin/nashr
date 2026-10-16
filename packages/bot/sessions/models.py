"""Typed objects for the brain editing session (Build 2, Stage 4).

These are pure value types: the session the chat loop loads/mutates/persists, the
approval-gate state, and the per-turn outcome that is the seam Stage 5's real
brain implements. No I/O lives here — persistence is in
:mod:`packages.bot.sessions.store`, the cap in :mod:`packages.bot.sessions.budget`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from google.genai import types as genai_types
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from packages.bot.orchestrators.article_orchestrator import SourceProcessingResult
from packages.core.enums import ExportFormat, GenerationPackage
from packages.core.models.presentation import DeckSpec, SlideFix


class ApprovalState(StrEnum):
    """Code-side approval-gate state, persisted on the session row.

    The DB value is the durable truth; the FSM ``awaiting_approval`` state is the
    live routing pointer derived from it on recovery.
    """

    IDLE = "idle"
    AWAITING_APPROVAL = "awaiting_approval"


class TurnAction(StrEnum):
    """What one brain turn produced — DESCRIPTIVE only, never an approval input.

    ``REPLY`` is a turn with no deck change; ``FIX`` is a turn that re-delivers a
    batch of slide edits. Deliberately has NO "propose" member: whether a
    re-delivery needs the approval button is decided by :func:`requires_approval`
    from the turn's PROVENANCE (a code-supplied observable), never from a label
    the model chooses — a model that could mark its own change "pre-approved"
    would defeat the gate. The machinery branches on ``bool(outcome.fixes)``, not
    on this label.
    """

    REPLY = "reply"  # answer the user; no deck change
    FIX = "fix"  # re-deliver a batch of slide edits


class PendingAction(BaseModel):
    """A proposed re-delivering change parked behind the approval gate.

    Persisted to ``brain_sessions.pending_action_json`` so the approve callback
    fires the EXACT proposed change even across a bot restart. The model never
    grants itself approval — only the user's button press does — so this records
    WHAT would be applied, not that it WAS.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fixes: list[SlideFix] = Field(min_length=1, max_length=20)
    reason: str = Field(default="", max_length=2000)
    # Number of edit_slides CALL parts in the parked model turn (>= 1). The approve
    # and reject paths must emit exactly this many function_response parts to answer
    # the parked call fully (Gemini requires one response per call). Defaults to 1
    # for the common single-call fix.
    call_count: int = Field(default=1, ge=1)


@dataclass(frozen=True)
class TurnOutcome:
    """The result of ONE brain turn — the seam Stage 5's real brain implements.

    A frozen dataclass, not a pydantic model, for the same reason as
    :class:`packages.core.gemini_tools.ToolTurnResult`: it carries live SDK
    ``Content`` objects (bytes-bearing) that must not be re-validated. ``history``
    is the FULL updated conversation the machinery persists verbatim via
    :func:`packages.core.gemini_tools.serialize_history`; ``estimated_cost_usd``
    is the turn's own LLM spend the budget cap charges before any tool fires.
    ``fixes`` is populated when the turn re-delivers; ``reply_text`` carries a
    plain answer, and ``reason`` the human-facing note shown at the approval gate.
    Whether a re-delivery needs the button is decided by the chat loop's
    provenance (see :func:`requires_approval`), never by anything on this object.
    """

    action: TurnAction
    history: list[genai_types.Content]
    estimated_cost_usd: float = 0.0
    reply_text: str | None = None
    fixes: tuple[SlideFix, ...] = ()
    reason: str | None = None
    # Number of edit_slides CALL parts in this turn (>= 1 when ``fixes`` is set, else
    # 0). Carried so the dispatch layer answers every call part with its own
    # function_response part — Gemini requires one response per call.
    fix_call_count: int = 0


class PendingDelivery(BaseModel):
    """An AI edit committed by a queued job whose exports are still rendering.

    A view of a ``reserved`` edit_deliveries row (B1-FIX3): it holds one fix of the
    allowance until the render delivers it (counted) or fails for good (released).
    The database settles it; the session only reads it.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1, max_length=64)
    revision_id: str = Field(min_length=1, max_length=64)
    slides_changed: int = Field(ge=0, le=1000)


class DeliveryNoteKind(StrEnum):
    """How a pending delivery settled."""

    DELIVERED = "delivered"
    FAILED = "failed"


class DeliveryNote(BaseModel):
    """A chat line the system owes the user about a settled delivery.

    ``history_index`` is ``len(history)`` when it settled, so the chat view shows
    it after the conversation turns that preceded it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: DeliveryNoteKind
    job_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=500)
    history_index: int = Field(ge=0)


class BrainSession(BaseModel):
    """The live, typed session a chat-loop turn loads, mutates, and persists.

    Recoverable from ``project_id`` alone — the ``brain_sessions`` row is unique
    on it, so no restart can orphan a session (the data survives; only the FSM
    pointer may be wiped). ``sources`` carries an EMPTY ``figures`` list on the
    light per-turn load; the chat loop hydrates figures only when a fix tool is
    about to fire (:func:`packages.bot.sessions.store.hydrate_figures`), so a
    text-only turn never deserializes the megabytes of raster bytes.
    ``figures_loaded`` records whether ``sources.figures`` is the real, hydrated
    set so a fix never grounds against an accidentally-empty figure roster.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    project_id: str = Field(min_length=1)
    history: list[genai_types.Content] = Field(default_factory=list[genai_types.Content])
    sources: SourceProcessingResult
    # The revision being edited (ADR 0001). ``deck`` is that revision's content,
    # loaded from it rather than from the head, so an edit always commits against
    # the deck the brain actually saw.
    revision_id: str | None = None
    deck: DeckSpec | None = None
    package: GenerationPackage
    formats: list[ExportFormat] = Field(min_length=1)
    approval_state: ApprovalState = ApprovalState.IDLE
    pending_action: PendingAction | None = None
    # The identity of the edit_slides call parked unanswered at the end of the
    # history (B1-FIX4): a queued edit names it, the database admits the edit only
    # while it is parked, and whatever answers the call clears it.
    parked_operation_id: str | None = None
    # The edit allowance is a COUNTER (see budget.has_fixes_remaining) of DELIVERED
    # edits, so a refused/failed fix never consumes one. Two sources (B1-FIX3):
    # ``inline_fixes_used`` is brain_sessions.fixes_used, written only by the bot's
    # inline edit path (and pre-016 history); ``delivered_edits`` counts this
    # session's delivered edit_deliveries rows and is never stored.
    inline_fixes_used: int = Field(default=0, ge=0)
    delivered_edits: int = Field(default=0, ge=0)
    # Reserved edit_deliveries rows: edits committed, still rendering, each holding
    # one fix until the database settles it.
    pending_deliveries: list[PendingDelivery] = Field(default_factory=list[PendingDelivery])
    # Notices already folded into the session (brain_sessions.delivery_notes_json).
    delivery_notes: list[DeliveryNote] = Field(default_factory=list[DeliveryNote], max_length=50)
    # Notices of settled rows no session write has folded in yet: shown by readers,
    # folded (and acknowledged) by the next write.
    unfolded_notes: list[DeliveryNote] = Field(default_factory=list[DeliveryNote])
    # ACTUAL spend, for billing/analytics ONLY — does not gate the session.
    accumulated_cost_usd: float = Field(default=0.0, ge=0.0)
    accumulated_image_count: int = Field(default=0, ge=0)
    figures_loaded: bool = False
    # The row this session was read from, and its compare-and-swap version.
    session_id: str | None = None
    version: int = Field(default=0, ge=0)
    # The persisted column values as they were read: the base of a three-way merge
    # when a write loses its compare-and-swap (store.persist_session).
    _base: dict[str, object] | None = PrivateAttr(default=None)

    @property
    def fixes_used(self) -> int:
        """Delivered edits: inline (bot, legacy) plus delivered queued edits."""

        return self.inline_fixes_used + self.delivered_edits


def requires_approval(outcome: TurnOutcome, *, user_initiated: bool) -> bool:
    """Decide IN CODE whether a re-delivery must be gated behind the user button.

    The axis is NOT the model's ``TurnAction`` label and NOT the batch size — a
    real brain could relabel a sweeping change as a routine fix, or keep a
    significant rewrite to one slide, and either would dodge a label/size gate.
    The axis is: did a HUMAN ACTION authorize THIS re-delivery? The only input is
    ``user_initiated`` — a provenance fact the chat loop supplies, which the model
    cannot set.

    * A turn with no fixes never re-delivers, so it never gates.
    * A user-initiated edit (the user's own message asked for this change) is
      authorized by the asking — no button.
    * Anything the model re-delivers on its OWN initiative requires the button,
      regardless of how it labels the turn or how many slides it touches.

    Stage 5 seam: when ``findings_json`` is populated, a fix that corresponds to
    a real critic finding is the OTHER human-action-equivalent observable that
    authorizes skipping the button (the fabrication-fix, fix-first path). That
    observable is added HERE — as an additional ``or`` on an observable the model
    cannot forge — without re-architecting. In Stage 4 findings are empty, so
    user-initiation is the sole authorizer.
    """

    if not outcome.fixes:
        return False
    return not user_initiated
