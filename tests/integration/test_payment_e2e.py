"""End-to-end payment test.

Simulates the user-facing payment lifecycle: create_invoice →
PerformTransaction webhook → mark_invoice_paid → grant_paid_credit. The
:class:`InvoiceService` is exercised against ``AsyncMock``-spec'd
:class:`DatabaseClient` and :class:`CreditLedger`; we never mock the
service itself.

Gated on ``RUN_E2E_TESTS=1`` to keep the default suite fast.
"""

from __future__ import annotations

import os
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.invoices import InvoiceService

E2E = os.environ.get("RUN_E2E_TESTS") == "1"


def _db_mock() -> MagicMock:
    """Build a ``DatabaseClient``-spec'd mock with the invoice paths pre-stubbed."""

    mock = MagicMock(spec=DatabaseClient)
    mock.get_pending_invoice = AsyncMock(return_value=None)
    mock.mark_invoice_expired = AsyncMock(return_value=None)
    mock.create_invoice = AsyncMock(return_value={})
    mock.mark_invoice_paid = AsyncMock(return_value=None)
    mock.get_invoice_by_number = AsyncMock(return_value=None)
    mock.expire_old_invoices = AsyncMock(return_value=0)
    return mock


def _credits_mock() -> MagicMock:
    mock = MagicMock(spec=CreditLedger)
    mock.grant_paid_credit = AsyncMock(return_value=None)
    return mock


@pytest.mark.skipif(not E2E, reason="RUN_E2E_TESTS not set")
class TestPaymentE2E:
    """Full lifecycle: create → webhook → credit grant."""

    async def test_invoice_to_payment_to_credit(self) -> None:
        """create_invoice → process_payment grants exactly one credit."""

        db = _db_mock()
        credits = _credits_mock()
        invoice_row: dict[str, Any] = {
            "id": "inv1",
            "invoice_number": "847291-1234",
            "user_id": "u1",
            "project_id": "p1",
            "amount_uzs": 60_000,
            "product_type": "article_basic",
            "status": "pending",
        }
        db.create_invoice.return_value = invoice_row
        svc = InvoiceService(cast(Any, db), cast(Any, credits))

        created = await svc.create_invoice(
            user_id="u1", project_id="p1", product_type="article_basic"
        )
        assert created["invoice_number"] == "847291-1234"

        # The webhook calls process_payment with the provider+reference;
        # service looks the invoice back up and then grants the credit.
        db.get_invoice_by_number.side_effect = [
            invoice_row,
            {**invoice_row, "status": "paid"},
        ]
        result = await svc.process_payment(
            invoice_number="847291-1234",
            payment_provider="payme",
            payment_reference="TXN-9001",
            amount_uzs=60_000,
        )

        credits.grant_paid_credit.assert_awaited_once_with(
            user_id="u1",
            amount_uzs=60_000,
            payment_reference="payme:TXN-9001",
        )
        assert result["status"] == "paid"

    async def test_double_payment_idempotent(self) -> None:
        """A second PerformTransaction for an already-paid invoice grants no extra credit."""

        db = _db_mock()
        credits = _credits_mock()
        paid_invoice: dict[str, Any] = {
            "id": "inv1",
            "invoice_number": "847291-1234",
            "user_id": "u1",
            "project_id": "p1",
            "amount_uzs": 60_000,
            "product_type": "article_basic",
            "status": "paid",
        }
        db.get_invoice_by_number.return_value = paid_invoice
        svc = InvoiceService(cast(Any, db), cast(Any, credits))

        result1 = await svc.process_payment(
            invoice_number="847291-1234",
            payment_provider="payme",
            payment_reference="TXN-9001",
            amount_uzs=60_000,
        )
        result2 = await svc.process_payment(
            invoice_number="847291-1234",
            payment_provider="payme",
            payment_reference="TXN-9001",
            amount_uzs=60_000,
        )

        # Idempotency: both calls return paid; no grants beyond the first run.
        assert result1["status"] == "paid"
        assert result2["status"] == "paid"
        credits.grant_paid_credit.assert_not_called()
        db.mark_invoice_paid.assert_not_called()

    async def test_invoice_expiry_blocks_payment(self) -> None:
        """An expired invoice raises rather than granting a credit."""

        db = _db_mock()
        credits = _credits_mock()
        expired_invoice: dict[str, Any] = {
            "id": "inv1",
            "invoice_number": "847291-1234",
            "user_id": "u1",
            "project_id": "p1",
            "amount_uzs": 60_000,
            "product_type": "article_basic",
            "status": "expired",
        }
        db.get_invoice_by_number.return_value = expired_invoice
        svc = InvoiceService(cast(Any, db), cast(Any, credits))

        with pytest.raises(ValueError, match="expired"):
            await svc.process_payment(
                invoice_number="847291-1234",
                payment_provider="payme",
                payment_reference="TXN-9001",
                amount_uzs=60_000,
            )
        credits.grant_paid_credit.assert_not_called()

    async def test_amount_mismatch_blocks_credit(self) -> None:
        """Provider amount mismatch raises and grants no credit."""

        db = _db_mock()
        credits = _credits_mock()
        invoice: dict[str, Any] = {
            "id": "inv1",
            "invoice_number": "847291-1234",
            "user_id": "u1",
            "project_id": "p1",
            "amount_uzs": 60_000,
            "product_type": "article_basic",
            "status": "pending",
        }
        db.get_invoice_by_number.return_value = invoice
        svc = InvoiceService(cast(Any, db), cast(Any, credits))

        with pytest.raises(ValueError, match="Amount"):
            await svc.process_payment(
                invoice_number="847291-1234",
                payment_provider="payme",
                payment_reference="TXN-9001",
                amount_uzs=50_000,  # wrong
            )
        credits.grant_paid_credit.assert_not_called()
        db.mark_invoice_paid.assert_not_called()
