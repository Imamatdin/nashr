"""Credits + pricing reads (Session W, P1.3).

Read-only by design: this run adds NO top-up, invoice or order surface (the
merchant question is open), so the web can finally SHOW the money — balance,
history, refunds, learning rewards, and what each tier actually costs and
contains — without gaining a way to spend.

``GET /pricing`` exists so the web stops carrying its own price table. The
authority is :data:`CreditLedger.PRICING` — the dict the enqueue route charges
from — joined with the two per-tier facts the approval card has to state:
the generated-image budget (SPEC §8) and the post-delivery fix allowance.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict

from packages.api.middleware.auth import Authenticated
from packages.bot.sessions.budget import session_fix_limit
from packages.core.constants import image_budget_for_package
from packages.core.enums import GenerationPackage
from packages.platform.credits import CreditLedger

router = APIRouter(tags=["credits"])

_DEFAULT_LEDGER_LIMIT = 25
_MAX_LEDGER_LIMIT = 100

# The tiers this API can actually sell today (the enqueue route's map). Article
# tiers are priced in the ledger but have no web surface, so listing them here
# would advertise something no route can start.
_WEB_PACKAGES: tuple[GenerationPackage, ...] = (
    GenerationPackage.PRESENTATION_BASIC,
    GenerationPackage.PRESENTATION_STANDARD,
    GenerationPackage.PRESENTATION_PREMIUM,
)


class BalanceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balance: int
    currency: str = "UZS"


class LedgerEntryView(BaseModel):
    """One ledger row, shaped for a human-readable history.

    ``action`` is what the UI branches on; ``reason`` is the coarse legacy
    descriptor migration 001's CHECK constraint pins the column to. A refund
    carries ``generation_job_id`` when the worker stamped it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    amount: int
    action: str
    reason: str
    project_id: str | None
    generation_job_id: str | None
    created_at: datetime


class LedgerView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    balance: int
    entries: list[LedgerEntryView]


class PricingEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package: str
    price: int
    ai_images: int
    fix_allowance: int


class PricingView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = "UZS"
    packages: list[PricingEntry]
    free_credit_value: int
    free_daily_cap: int
    free_weekly_cap: int
    free_project_cap: int


@router.get("/credits", response_model=BalanceView)
async def get_credits(request: Request, auth: Authenticated) -> BalanceView:
    """The caller's confirmed balance in UZS."""

    credits: CreditLedger = request.app.state.credits
    return BalanceView(balance=await credits.get_balance(str(auth.user_id)))


@router.get("/credits/ledger", response_model=LedgerView)
async def get_credit_ledger(
    request: Request,
    auth: Authenticated,
    limit: int = Query(default=_DEFAULT_LEDGER_LIMIT, ge=1, le=_MAX_LEDGER_LIMIT),
) -> LedgerView:
    """Recent ledger rows, newest first, plus the balance they sum to.

    The balance is computed over the FULL history, not the returned page — a
    truncated list must never imply a smaller balance.
    """

    credits: CreditLedger = request.app.state.credits
    user_id = str(auth.user_id)
    entries = await credits.get_ledger(user_id, limit=limit)
    return LedgerView(
        balance=await credits.get_balance(user_id),
        entries=[
            LedgerEntryView(
                id=entry.id,
                amount=entry.amount,
                action=entry.action.value,
                reason=entry.reason,
                project_id=entry.project_id,
                generation_job_id=entry.generation_job_id,
                created_at=entry.created_at,
            )
            for entry in entries
        ],
    )


@router.get("/pricing", response_model=PricingView)
async def get_pricing() -> PricingView:
    """The canonical tier table — price, image budget, fix allowance.

    Unauthenticated: prices are public, and the approval card needs them before
    a first-time user has done anything. Free-credit caps ride along so the
    reward copy can state the real limits instead of guessing.
    """

    return PricingView(
        packages=[
            PricingEntry(
                package=package.value,
                price=CreditLedger.PRICING[package.value],
                ai_images=image_budget_for_package(package),
                fix_allowance=session_fix_limit(package),
            )
            for package in _WEB_PACKAGES
        ],
        free_credit_value=CreditLedger.FREE_CREDIT_VALUE,
        free_daily_cap=CreditLedger.FREE_DAILY_CAP,
        free_weekly_cap=CreditLedger.FREE_WEEKLY_CAP,
        free_project_cap=CreditLedger.FREE_PROJECT_CAP,
    )


__all__ = ["router"]
