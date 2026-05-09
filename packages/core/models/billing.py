"""Billing models: append-only credit ledger, payment orders, and generation jobs."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from packages.core.enums import (
    CreditReason,
    CreditStatus,
    GenerationPackage,
    JobStatus,
    JobType,
    OrderStatus,
    PaymentProvider,
)


class CreditLedgerEntry(BaseModel):
    """One row in the append-only credit ledger.

    Positive ``amount`` adds credits, negative subtracts. Balance is computed
    as ``SUM(amount) WHERE status = 'confirmed'``; rows are never updated or
    deleted.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    amount: int = Field(description="Signed credit delta; positive add, negative spend.")
    reason: CreditReason
    order_id: UUID | None = None
    generation_job_id: UUID | None = None
    status: CreditStatus = CreditStatus.CONFIRMED
    created_at: datetime


class Order(BaseModel):
    """A user-initiated payment order routed through Payme/Click."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    amount_uzs: int = Field(gt=0, le=100_000_000)
    package_type: GenerationPackage
    payment_provider: PaymentProvider
    payment_id: str | None = Field(default=None, max_length=200)
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime
    paid_at: datetime | None = None


class GenerationJob(BaseModel):
    """A unit of background work tracked end-to-end with cost telemetry."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    job_type: JobType
    status: JobStatus = JobStatus.QUEUED
    estimated_cost_uzs: int = Field(ge=0)
    actual_cost_uzs: int = Field(default=0, ge=0)
    model_calls_count: int = Field(default=0, ge=0)
    image_count: int = Field(default=0, ge=0)
    input_tokens_total: int = Field(default=0, ge=0)
    output_tokens_total: int = Field(default=0, ge=0)
    error_message: str | None = Field(default=None, max_length=4000)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
