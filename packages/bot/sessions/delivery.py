"""Settle AI edits whose exports render asynchronously (B1-FIX2).

A queued web edit commits its revision in the job's transaction and leaves the
job ``committed`` while a render job publishes the exports. The edit is
*delivered* only when that render succeeds, so the session holds one fix of the
allowance for it (a :class:`PendingDelivery`) until the job settles:

* ``completed``: the exports are published; the fix is counted and the chat says
  the edit is ready.
* ``delivery_failed`` (or any other end without delivery): the hold is released,
  so the allowance is restored, and the chat says the edit was saved but its
  files could not be produced.

Settlement reads the job row, which the database settles in the same
transaction as the render's own outcome, so it is correct whoever ended the
render: the worker, a retry, or the reaper. It runs whenever a session is loaded
and is idempotent: a settled hold is gone, so it is never counted twice.
"""

from __future__ import annotations

import logging
from typing import Final

from packages.bot.sessions.models import (
    BrainSession,
    DeliveryNote,
    DeliveryNoteKind,
    PendingDelivery,
)
from packages.core.enums import Language
from packages.platform.jobs import JobQueue, JobStatus

logger = logging.getLogger(__name__)

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

# Job states that still mean "the render may yet deliver".
_IN_FLIGHT: Final[frozenset[JobStatus]] = frozenset(
    {JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.COMMITTED}
)


def delivery_note_text(language: Language, kind: DeliveryNoteKind, slides_changed: int) -> str:
    """The localized chat line for one settled delivery."""

    return _NOTES[language][kind].format(n=slides_changed)


def fixes_reserved(session: BrainSession) -> int:
    """Fixes the allowance is already spoken for: delivered plus still rendering."""

    return session.fixes_used + len(session.pending_deliveries)


async def settle_deliveries(queue: JobQueue, session: BrainSession) -> bool:
    """Settle every pending delivery whose job has ended; True when the session changed."""

    if not session.pending_deliveries:
        return False
    language = session.deck.language if session.deck is not None else Language.UZ
    still_pending: list[PendingDelivery] = []
    changed = False
    for pending in session.pending_deliveries:
        job = await queue.get_job(pending.job_id)
        if job is not None and job.status in _IN_FLIGHT:
            still_pending.append(pending)
            continue
        delivered = job is not None and job.status is JobStatus.COMPLETED
        kind = DeliveryNoteKind.DELIVERED if delivered else DeliveryNoteKind.FAILED
        if delivered:
            session.fixes_used += 1
        session.delivery_notes = [
            *session.delivery_notes,
            DeliveryNote(
                kind=kind,
                job_id=pending.job_id,
                text=delivery_note_text(language, kind, pending.slides_changed),
                history_index=len(session.history),
            ),
        ][-_MAX_NOTES:]
        logger.info(
            "edit_delivery_settled project=%s job=%s status=%s",
            session.project_id,
            pending.job_id,
            job.status.value if job is not None else "missing",
        )
        changed = True
    session.pending_deliveries = still_pending
    return changed


_MAX_NOTES: Final[int] = 50

__all__ = ["delivery_note_text", "fixes_reserved", "settle_deliveries"]
