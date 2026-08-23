"""Append-only credit ledger for the Nashr platform.

A user's balance is the signed sum of every ledger row that belongs to
them. Rows are never updated or deleted; refunds and reversals are
expressed as new entries. This keeps the audit trail intact and removes
an entire class of accounting bugs (lost updates, partial writes).

The ledger is the single source of truth for "can this user generate
another article?" decisions; payment webhooks and free-credit grants
both write through the same code path.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field

from packages.platform.database import DatabaseClient


class CreditAction(StrEnum):
    """Reason a credit ledger row was written.

    Values are wire-stable and match the ``credit_ledger.action`` CHECK
    constraint in migration 002.
    """

    GRANT_FREE = "grant_free"
    GRANT_PAID = "grant_paid"
    DEDUCT_ARTICLE = "deduct_article"
    DEDUCT_PRESENTATION = "deduct_presentation"
    REFUND = "refund"


class FreeCreditsReason(StrEnum):
    """The research behaviour that earned a free credit.

    Free credits are awarded for actions that improve evidence quality;
    they are not a participation prize for opening the bot. Each value
    here maps to a single observable user event so the bot can pass it
    straight through to :meth:`CreditLedger.grant_free_credit`.
    """

    SOURCE_UPLOAD = "source_upload"
    INTERVIEW_ANSWER = "interview_answer"
    CONTRADICTION_EXPLAIN = "contradiction_explain"
    DAILY_BONUS = "daily_bonus"


_ACTION_TO_REASON: dict[CreditAction, str] = {
    CreditAction.GRANT_FREE: "learning_reward",
    CreditAction.GRANT_PAID: "payment",
    CreditAction.DEDUCT_ARTICLE: "article_generation",
    CreditAction.DEDUCT_PRESENTATION: "presentation_generation",
    CreditAction.REFUND: "refund",
}


class CreditEntry(BaseModel):
    """A single row in the append-only credit ledger.

    Positive ``amount`` adds credits, negative subtracts. The ``reason``
    field is a short human-readable descriptor (e.g. "source upload",
    "article_basic generation"); the structured ``action`` is what the
    code branches on.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str = ""
    user_id: str
    project_id: str | None = None
    # The job this row settles, when there is one. ``reason`` cannot carry it:
    # migration 001's CHECK constraint pins that column to five fixed values,
    # so the detail a caller passes is mapped away by ``_ACTION_TO_REASON``.
    # This is the only exact link between a failed job and its refund row.
    generation_job_id: str | None = None
    action: CreditAction
    amount: int
    reason: str = Field(max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InsufficientCreditsError(Exception):
    """Raised when a deduction would push the user's balance below zero.

    Carries both the current balance and the required amount so the
    caller (typically the Telegram bot) can compose a useful payment
    prompt without re-querying the ledger.
    """

    def __init__(self, balance: int, required: int) -> None:
        self.balance = balance
        self.required = required
        super().__init__(f"Insufficient credits: balance {balance} UZS, required {required} UZS")


class CreditLedger:
    """Manages credit grants, deductions, and refunds for every user.

    Pricing (UZS):
      Articles: basic 60 000 / standard 90 000 / premium 150 000
      Presentations: basic 5 000 / standard 10 000 / premium 15 000

    Free credits:
      Each research action earns one free credit worth 5 000 UZS — enough
      to cover a basic presentation. Caps prevent farming: 3 per day,
      10 per week, 5 per project.

    The underlying table is append-only; balance is recomputed from the
    full history on every read. At realistic ledger sizes (< 10 000
    rows per user) this is fast enough; we add a caching layer only if
    measurement says we need one.
    """

    PRICING: ClassVar[dict[str, int]] = {
        "article_basic": 60_000,
        "article_standard": 90_000,
        "article_premium": 150_000,
        "presentation_basic": 5_000,
        "presentation_standard": 10_000,
        "presentation_premium": 15_000,
    }

    FREE_CREDIT_VALUE: ClassVar[int] = 5_000
    FREE_DAILY_CAP: ClassVar[int] = 3
    FREE_WEEKLY_CAP: ClassVar[int] = 10
    FREE_PROJECT_CAP: ClassVar[int] = 5

    def __init__(self, db: DatabaseClient, *, dev_mode: bool = False) -> None:
        self._db = db
        self._dev_mode = dev_mode

    @property
    def dev_mode(self) -> bool:
        """Whether balance checks are bypassed for development testing."""

        return self._dev_mode

    # ---------------------------------------------------------- balance API

    async def get_balance(self, user_id: str) -> int:
        """Return the user's current confirmed balance in UZS."""

        rows = await self._fetch_user_entries(user_id)
        return sum(int(row.get("amount", 0)) for row in rows)

    async def has_sufficient_credits(self, user_id: str, product_type: str) -> bool:
        """Return True iff the user's balance covers the given product price.

        In dev mode this always returns True so end-to-end flows can run
        without paid credits; the ledger entry is still recorded by
        :meth:`deduct_for_generation` so audit trails stay intact.
        """

        if self._dev_mode:
            return True
        price = self.PRICING[product_type]
        balance = await self.get_balance(user_id)
        return balance >= price

    # ----------------------------------------------------------- grants API

    async def grant_free_credit(
        self,
        user_id: str,
        project_id: str,
        reason: FreeCreditsReason,
    ) -> CreditEntry | None:
        """Grant one free credit if the user is below every cap.

        Returns the new ledger entry, or ``None`` if any cap (daily,
        weekly, per-project) has been reached. The caps are checked in
        that order so the bot can surface the tightest constraint when
        we need to.
        """

        if await self.get_free_credits_today(user_id) >= self.FREE_DAILY_CAP:
            return None
        if await self.get_free_credits_this_week(user_id) >= self.FREE_WEEKLY_CAP:
            return None
        if await self.get_free_credits_for_project(user_id, project_id) >= self.FREE_PROJECT_CAP:
            return None

        entry = CreditEntry(
            user_id=user_id,
            project_id=project_id,
            action=CreditAction.GRANT_FREE,
            amount=self.FREE_CREDIT_VALUE,
            reason=reason.value,
        )
        return await self._insert(entry)

    async def grant_paid_credit(
        self,
        user_id: str,
        amount_uzs: int,
        payment_reference: str,
    ) -> CreditEntry:
        """Record a paid credit grant. No caps."""

        entry = CreditEntry(
            user_id=user_id,
            project_id=None,
            action=CreditAction.GRANT_PAID,
            amount=amount_uzs,
            reason=f"payment:{payment_reference}",
        )
        return await self._insert(entry)

    # -------------------------------------------------------- deduction API

    async def deduct_for_generation(
        self,
        user_id: str,
        project_id: str,
        product_type: str,
    ) -> CreditEntry:
        """Deduct the price of ``product_type`` from the user's balance.

        Raises :class:`InsufficientCreditsError` if the balance is below
        the price; the error carries the exact deficit so the bot can
        offer a top-up immediately. In dev mode the balance check is
        skipped — the deduction row is still written (so the audit
        trail / cost telemetry remain intact) but the operation never
        rejects.
        """

        price = self.PRICING[product_type]
        if not self._dev_mode:
            balance = await self.get_balance(user_id)
            if balance < price:
                raise InsufficientCreditsError(balance=balance, required=price)
        action = (
            CreditAction.DEDUCT_ARTICLE
            if product_type.startswith("article")
            else CreditAction.DEDUCT_PRESENTATION
        )
        reason_prefix = "dev_generation" if self._dev_mode else "generation"
        entry = CreditEntry(
            user_id=user_id,
            project_id=project_id,
            action=action,
            amount=-price,
            reason=f"{reason_prefix}:{product_type}",
        )
        return await self._insert(entry)

    async def refund(
        self,
        user_id: str,
        project_id: str,
        amount_uzs: int,
        reason: str,
        *,
        generation_job_id: str | None = None,
    ) -> CreditEntry:
        """Issue a positive-amount refund row.

        ``generation_job_id`` is what makes :meth:`has_refund_for_job` exact —
        pass it whenever the refund settles a specific job. Deliberately NOT
        passed by the enqueue route's lost-race refund: that undoes the LOSING
        deduction while the winning job's own charge stands, so stamping the
        winner's id would make it report itself refunded.
        """

        entry = CreditEntry(
            user_id=user_id,
            project_id=project_id,
            generation_job_id=generation_job_id,
            action=CreditAction.REFUND,
            amount=amount_uzs,
            reason=reason,
        )
        return await self._insert(entry)

    async def has_refund_for_job(self, user_id: str, generation_job_id: str) -> bool:
        """True iff a refund row is stamped with this job id.

        Rows written before the stamp existed carry NULL, so a pre-deploy
        failed job answers False — an honest "no evidence of a refund" rather
        than a guess from timestamps.
        """

        def run() -> Any:
            return (
                self._db._query("credit_ledger")  # pyright: ignore[reportPrivateUsage]
                .select("id")
                .eq("user_id", user_id)
                .eq("generation_job_id", generation_job_id)
                .eq("action", CreditAction.REFUND.value)
                .limit(1)
                .execute()
            )

        result = await asyncio.to_thread(run)
        return bool(result.data)

    # ---------------------------------------------------------- cap helpers

    async def get_free_credits_today(self, user_id: str) -> int:
        """Count the GRANT_FREE entries for ``user_id`` since 00:00 UTC."""

        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return await self._count_free_since(user_id, start)

    async def get_free_credits_this_week(self, user_id: str) -> int:
        """Count GRANT_FREE entries for ``user_id`` since Monday 00:00 UTC."""

        now = datetime.now(UTC)
        start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_week = start_of_today - timedelta(days=now.weekday())
        return await self._count_free_since(user_id, start_of_week)

    async def get_free_credits_for_project(self, user_id: str, project_id: str) -> int:
        """Count GRANT_FREE entries for the given user+project pair."""

        rows = await self._fetch_user_entries(user_id)
        return sum(
            1
            for r in rows
            if r.get("action") == CreditAction.GRANT_FREE.value
            and r.get("project_id") == project_id
        )

    async def get_ledger(self, user_id: str, limit: int = 50) -> list[CreditEntry]:
        """Return the user's recent ledger rows, newest first."""

        rows = await self._fetch_user_entries(user_id, limit=limit, desc=True)
        out: list[CreditEntry] = []
        for row in rows:
            out.append(self._row_to_entry(row))
        return out

    # ----------------------------------------------------------- internals

    async def _fetch_user_entries(
        self,
        user_id: str,
        *,
        limit: int | None = None,
        desc: bool = False,
    ) -> list[dict[str, Any]]:
        def run() -> Any:
            q = self._db._query("credit_ledger").select("*").eq("user_id", user_id)  # pyright: ignore[reportPrivateUsage]
            if desc:
                q = q.order("created_at", desc=True)
            if limit is not None:
                q = q.limit(limit)
            return q.execute()

        result = await asyncio.to_thread(run)
        return cast(list[dict[str, Any]], list(result.data))

    async def _count_free_since(self, user_id: str, since: datetime) -> int:
        rows = await self._fetch_user_entries(user_id)
        count = 0
        for row in rows:
            if row.get("action") != CreditAction.GRANT_FREE.value:
                continue
            created_raw = row.get("created_at")
            created = _parse_created_at(created_raw)
            if created is None:
                continue
            if created >= since:
                count += 1
        return count

    async def _insert(self, entry: CreditEntry) -> CreditEntry:
        payload: dict[str, Any] = {
            "user_id": entry.user_id,
            "amount": entry.amount,
            "action": entry.action.value,
            "reason": _ACTION_TO_REASON[entry.action],
        }
        if entry.project_id is not None:
            payload["project_id"] = entry.project_id
        if entry.generation_job_id is not None:
            payload["generation_job_id"] = entry.generation_job_id

        def run() -> Any:
            return self._db._query("credit_ledger").insert(payload).execute()  # pyright: ignore[reportPrivateUsage]

        result = await asyncio.to_thread(run)
        row = cast(dict[str, Any], result.data[0]) if result.data else {}
        if "id" in row:
            entry = entry.model_copy(update={"id": str(row["id"])})
        return entry

    @staticmethod
    def _row_to_entry(row: dict[str, Any]) -> CreditEntry:
        action_raw = row.get("action") or _legacy_reason_to_action(row.get("reason"))
        return CreditEntry(
            id=str(row.get("id", "")),
            user_id=str(row["user_id"]),
            project_id=(str(row["project_id"]) if row.get("project_id") is not None else None),
            generation_job_id=(
                str(row["generation_job_id"]) if row.get("generation_job_id") is not None else None
            ),
            action=CreditAction(action_raw),
            amount=int(row["amount"]),
            reason=str(row.get("reason", "")),
            created_at=_parse_created_at(row.get("created_at")) or datetime.now(UTC),
        )


def _parse_created_at(value: Any) -> datetime | None:
    """Coerce a Supabase-returned timestamp value into a tz-aware datetime."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return None


_LEGACY_REASON_TO_ACTION: dict[str, str] = {
    "payment": CreditAction.GRANT_PAID.value,
    "learning_reward": CreditAction.GRANT_FREE.value,
    "article_generation": CreditAction.DEDUCT_ARTICLE.value,
    "presentation_generation": CreditAction.DEDUCT_PRESENTATION.value,
    "refund": CreditAction.REFUND.value,
}


def _legacy_reason_to_action(reason: Any) -> str:
    """Map an older ``reason`` value (pre-action column) to a CreditAction string."""

    if isinstance(reason, str) and reason in _LEGACY_REASON_TO_ACTION:
        return _LEGACY_REASON_TO_ACTION[reason]
    return CreditAction.GRANT_FREE.value
