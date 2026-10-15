"""What the session knows about AI edits whose exports render asynchronously.

A queued web edit commits its revision in the job's transaction and leaves the
job ``committed`` while a render job publishes the exports. The edit is
*delivered* only when that render succeeds. Since B1-FIX3 the hold it takes on the
allowance is an ``edit_deliveries`` row written by migration 016 in the same
transactions that commit the edit and settle its render, so no worker crash or
lost session write can lose it (Codex A1):

* ``reserved``: committed, still rendering; it holds one fix;
* ``delivered``: the exports are published; the fix is counted and the chat says
  the edit is ready;
* ``released``: the render failed for good; the allowance is restored and the
  chat says the edit was saved but its files could not be produced.

This module only projects those rows onto a loaded session: the counts, the
holds, and the chat notice of each settled row that no session write has folded
in yet. Projecting is a pure read (Codex A2: a GET never writes).
"""

from __future__ import annotations

from typing import Final

from packages.bot.sessions.models import (
    BrainSession,
    DeliveryNote,
    DeliveryNoteKind,
    PendingDelivery,
)
from packages.core.enums import Language
from packages.platform.edit_deliveries import EditDelivery, EditDeliveryStatus

# What the chat tells the user, in the deck's language. ``{n}`` is the number of
# slides the edit changed.
_NOTES: Final[dict[Language, dict[DeliveryNoteKind, str]]] = {
    Language.UZ: {
        DeliveryNoteKind.DELIVERED: (
            "Tahrir tayyor: {n} ta slayd yangilandi, yuklab olish fayllari ham yangilandi."
        ),
        DeliveryNoteKind.FAILED: (
            "Tahrir saqlandi, lekin uning fayllarini tayyorlab bo'lmadi. Bu tahrir "
            "limitingizdan hisoblanmadi — qayta urinib ko'rishingiz mumkin."
        ),
    },
    Language.RU: {
        DeliveryNoteKind.DELIVERED: (
            "Правка готова: обновлено слайдов — {n}, файлы для скачивания тоже обновлены."
        ),
        DeliveryNoteKind.FAILED: (
            "Правка сохранена, но подготовить для неё файлы не удалось. Она не засчитана "
            "в лимит правок — можно попробовать ещё раз."
        ),
    },
    Language.KAA: {
        DeliveryNoteKind.DELIVERED: (
            "Ózgeris tayar: {n} slayd jańalandı, júklep alıw faylları da jańalandı."
        ),
        DeliveryNoteKind.FAILED: (
            "Ózgeris saqlandı, biraq onıń faylların tayarlaw múmkin bolmadı. Bul ózgeris "
            "limitińizden esaplanbadı — qaytadan urınıp kóriwińiz múmkin."
        ),
    },
    Language.EN: {
        DeliveryNoteKind.DELIVERED: (
            "Your edit is ready: {n} slide(s) updated, and the downloads are refreshed."
        ),
        DeliveryNoteKind.FAILED: (
            "Your edit was saved, but its files could not be produced. It was not counted "
            "against your edits, so you can try again."
        ),
    },
}


def delivery_note_text(language: Language, kind: DeliveryNoteKind, slides_changed: int) -> str:
    """The localized chat line for one settled delivery."""

    return _NOTES[language][kind].format(n=slides_changed)


def fixes_reserved(session: BrainSession) -> int:
    """Fixes the allowance is already spoken for: delivered plus still rendering."""

    return session.fixes_used + len(session.pending_deliveries)


def apply_deliveries(session: BrainSession, rows: list[EditDelivery]) -> None:
    """Project the session's edit_deliveries rows onto it (no I/O, no writes).

    Delivered rows are counted, reserved rows are holds, and every settled row
    whose notice is neither acknowledged nor already folded in becomes an unfolded
    notice placed after the conversation as it stands.
    """

    language = session.deck.language if session.deck is not None else Language.UZ
    folded = {note.job_id for note in session.delivery_notes}
    session.delivered_edits = sum(1 for row in rows if row.status is EditDeliveryStatus.DELIVERED)
    session.pending_deliveries = [
        PendingDelivery(
            job_id=row.job_id, revision_id=row.revision_id, slides_changed=row.slides_changed
        )
        for row in rows
        if row.status is EditDeliveryStatus.RESERVED
    ]
    unfolded: list[DeliveryNote] = []
    for row in sorted(rows, key=_settled_order):
        if row.status is EditDeliveryStatus.RESERVED:
            continue
        if row.notice_acknowledged or row.job_id in folded:
            continue
        kind = (
            DeliveryNoteKind.DELIVERED
            if row.status is EditDeliveryStatus.DELIVERED
            else DeliveryNoteKind.FAILED
        )
        unfolded.append(
            DeliveryNote(
                kind=kind,
                job_id=row.job_id,
                text=delivery_note_text(language, kind, row.slides_changed),
                history_index=len(session.history),
            )
        )
    session.unfolded_notes = unfolded


def fold_notes(session: BrainSession) -> list[str]:
    """Move unfolded notices into the persisted ones; returns their job ids.

    A writer calls this before it saves, so a notice keeps the place in the
    conversation where it was first shown, and acknowledges the ids after the save.
    """

    if not session.unfolded_notes:
        return []
    folded = [note.job_id for note in session.unfolded_notes]
    session.delivery_notes = [*session.delivery_notes, *session.unfolded_notes][-MAX_NOTES:]
    session.unfolded_notes = []
    return folded


def visible_notes(session: BrainSession) -> list[DeliveryNote]:
    """Every notice a reader shows: folded ones, then unfolded ones, once per job."""

    seen: set[str] = set()
    notes: list[DeliveryNote] = []
    for note in [*session.delivery_notes, *session.unfolded_notes]:
        if note.job_id in seen:
            continue
        seen.add(note.job_id)
        notes.append(note)
    return notes


def _settled_order(row: EditDelivery) -> str:
    stamp = row.settled_at or row.created_at
    return stamp.isoformat() if stamp is not None else ""


MAX_NOTES: Final[int] = 50

__all__ = [
    "MAX_NOTES",
    "apply_deliveries",
    "delivery_note_text",
    "fixes_reserved",
    "fold_notes",
    "visible_notes",
]
