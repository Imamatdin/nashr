"""Behaviour tests for :class:`packages.platform.invoices.InvoiceService`.

We hold the :class:`DatabaseClient` and :class:`CreditLedger`
collaborators at arm's length: the service is the unit under test, so
both dependencies are :class:`AsyncMock`-spec'd against the real
classes. The fixtures expose ``db_mock`` / ``credits_mock`` so each
test can stage the exact return values it needs without leaking shared
state across tests.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.invoices import InvoiceService


@pytest.fixture
def db_mock() -> MagicMock:
    """A spec'd :class:`DatabaseClient` mock with async stubs in place."""

    mock = MagicMock(spec=DatabaseClient)
    mock.get_pending_invoice = AsyncMock(return_value=None)
    mock.mark_invoice_expired = AsyncMock(return_value=None)
    mock.create_invoice = AsyncMock(return_value={})
    mock.mark_invoice_paid = AsyncMock(return_value=None)
    mock.get_invoice_by_number = AsyncMock(return_value=None)
    mock.expire_old_invoices = AsyncMock(return_value=0)
    return mock


@pytest.fixture
def credits_mock() -> MagicMock:
    """A spec'd :class:`CreditLedger` mock with an async grant stub."""

    mock = MagicMock(spec=CreditLedger)
    mock.grant_paid_credit = AsyncMock(return_value=None)
    return mock


def _service(db_mock: MagicMock, credits_mock: MagicMock) -> InvoiceService:
    return InvoiceService(cast(Any, db_mock), cast(Any, credits_mock))


# ---------------------------------------------------------------------------
# create_invoice
# ---------------------------------------------------------------------------


async def test_create_invoice_uses_pricing_table_and_returns_db_row(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    db_mock.create_invoice.return_value = {
        "id": "inv1",
        "invoice_number": "847291-1234",
        "amount_uzs": 60_000,
        "product_type": "article_basic",
        "status": "pending",
    }
    svc = _service(db_mock, credits_mock)

    result = await svc.create_invoice(user_id="u1", project_id="p1", product_type="article_basic")

    assert result["invoice_number"] == "847291-1234"
    assert result["status"] == "pending"
    db_mock.create_invoice.assert_awaited_once_with(
        user_id="u1",
        project_id="p1",
        amount_uzs=60_000,
        product_type="article_basic",
    )


async def test_create_invoice_expires_existing_pending(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    db_mock.get_pending_invoice.return_value = {"id": "old_inv", "status": "pending"}
    db_mock.create_invoice.return_value = {
        "id": "new_inv",
        "invoice_number": "847291-9999",
        "amount_uzs": 10_000,
        "status": "pending",
    }
    svc = _service(db_mock, credits_mock)

    await svc.create_invoice(user_id="u1", project_id="p1", product_type="presentation_standard")

    db_mock.mark_invoice_expired.assert_awaited_once_with("old_inv")
    db_mock.create_invoice.assert_awaited_once()


async def test_create_invoice_unknown_product_raises(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    svc = _service(db_mock, credits_mock)
    with pytest.raises(ValueError, match="Unknown product type"):
        await svc.create_invoice(user_id="u1", project_id="p1", product_type="nonexistent_tier")
    db_mock.create_invoice.assert_not_called()


async def test_create_invoice_price_lookup_matches_credit_ledger() -> None:
    """The invoice amount must equal CreditLedger.PRICING for every tier."""

    for tier, expected in CreditLedger.PRICING.items():
        db_mock = MagicMock(spec=DatabaseClient)
        db_mock.get_pending_invoice = AsyncMock(return_value=None)
        db_mock.mark_invoice_expired = AsyncMock(return_value=None)
        db_mock.create_invoice = AsyncMock(
            return_value={
                "id": "x",
                "invoice_number": "100000-0000",
                "amount_uzs": expected,
                "status": "pending",
            }
        )
        credits_mock = MagicMock(spec=CreditLedger)
        svc = InvoiceService(cast(Any, db_mock), cast(Any, credits_mock))
        await svc.create_invoice(user_id="u", project_id="p", product_type=tier)
        kwargs = db_mock.create_invoice.await_args.kwargs
        assert kwargs["amount_uzs"] == expected, f"{tier} should be {expected}"


# ---------------------------------------------------------------------------
# process_payment
# ---------------------------------------------------------------------------


def _pending_invoice(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "inv_id_1",
        "invoice_number": "847291-1234",
        "user_id": "u1",
        "project_id": "p1",
        "amount_uzs": 60_000,
        "product_type": "article_basic",
        "status": "pending",
    }
    base.update(overrides)
    return base


async def test_process_payment_marks_paid_and_grants_credit(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    invoice = _pending_invoice()
    db_mock.get_invoice_by_number.side_effect = [invoice, {**invoice, "status": "paid"}]
    svc = _service(db_mock, credits_mock)

    result = await svc.process_payment(
        invoice_number="847291-1234",
        payment_provider="payme",
        payment_reference="TXN-9001",
        amount_uzs=60_000,
    )

    db_mock.mark_invoice_paid.assert_awaited_once_with(
        invoice_id="inv_id_1",
        payment_provider="payme",
        payment_reference="TXN-9001",
    )
    credits_mock.grant_paid_credit.assert_awaited_once_with(
        user_id="u1",
        amount_uzs=60_000,
        payment_reference="payme:TXN-9001",
    )
    assert result["status"] == "paid"


async def test_process_payment_idempotent_when_already_paid(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    paid_invoice = _pending_invoice(status="paid")
    db_mock.get_invoice_by_number.return_value = paid_invoice
    svc = _service(db_mock, credits_mock)

    result = await svc.process_payment(
        invoice_number="847291-1234",
        payment_provider="payme",
        payment_reference="TXN-9001",
        amount_uzs=60_000,
    )

    db_mock.mark_invoice_paid.assert_not_called()
    credits_mock.grant_paid_credit.assert_not_called()
    assert result["status"] == "paid"


async def test_process_payment_expired_raises(db_mock: MagicMock, credits_mock: MagicMock) -> None:
    db_mock.get_invoice_by_number.return_value = _pending_invoice(status="expired")
    svc = _service(db_mock, credits_mock)

    with pytest.raises(ValueError, match="expired"):
        await svc.process_payment(
            invoice_number="847291-1234",
            payment_provider="payme",
            payment_reference="TXN",
            amount_uzs=60_000,
        )
    credits_mock.grant_paid_credit.assert_not_called()


async def test_process_payment_cancelled_raises(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    db_mock.get_invoice_by_number.return_value = _pending_invoice(status="cancelled")
    svc = _service(db_mock, credits_mock)

    with pytest.raises(ValueError, match="cancelled"):
        await svc.process_payment(
            invoice_number="847291-1234",
            payment_provider="payme",
            payment_reference="TXN",
            amount_uzs=60_000,
        )


async def test_process_payment_amount_mismatch_raises(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    db_mock.get_invoice_by_number.return_value = _pending_invoice(amount_uzs=60_000)
    svc = _service(db_mock, credits_mock)

    with pytest.raises(ValueError, match="Amount mismatch"):
        await svc.process_payment(
            invoice_number="847291-1234",
            payment_provider="payme",
            payment_reference="TXN",
            amount_uzs=50_000,
        )
    db_mock.mark_invoice_paid.assert_not_called()
    credits_mock.grant_paid_credit.assert_not_called()


async def test_process_payment_not_found_raises(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    db_mock.get_invoice_by_number.return_value = None
    svc = _service(db_mock, credits_mock)

    with pytest.raises(ValueError, match="Invoice not found"):
        await svc.process_payment(
            invoice_number="000000-0000",
            payment_provider="payme",
            payment_reference="TXN",
            amount_uzs=60_000,
        )


# ---------------------------------------------------------------------------
# generate_deep_link
# ---------------------------------------------------------------------------


def test_generate_deep_link_payme_uses_tiyin(db_mock: MagicMock, credits_mock: MagicMock) -> None:
    svc = _service(db_mock, credits_mock)
    url = svc.generate_deep_link(provider="payme", invoice_number="847291-1001", amount_uzs=60_000)

    assert "payme.uz" in url
    assert "amount=6000000" in url
    assert "847291-1001" in url


def test_generate_deep_link_click_uses_uzs(db_mock: MagicMock, credits_mock: MagicMock) -> None:
    svc = _service(db_mock, credits_mock)
    url = svc.generate_deep_link(provider="click", invoice_number="847291-1001", amount_uzs=60_000)

    assert "click.uz" in url
    assert "amount=60000" in url
    assert "847291-1001" in url


def test_generate_deep_link_uzum_uses_uzs(db_mock: MagicMock, credits_mock: MagicMock) -> None:
    svc = _service(db_mock, credits_mock)
    url = svc.generate_deep_link(provider="uzum", invoice_number="847291-1001", amount_uzs=15_000)

    assert "uzumbank.uz" in url
    assert "amount=15000" in url
    assert "847291-1001" in url


def test_generate_deep_link_unknown_provider_returns_empty(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    svc = _service(db_mock, credits_mock)
    assert (
        svc.generate_deep_link(provider="humo", invoice_number="847291-1001", amount_uzs=60_000)
        == ""
    )


# ---------------------------------------------------------------------------
# check_and_expire_old_invoices / get_invoice_status
# ---------------------------------------------------------------------------


async def test_check_and_expire_old_invoices_returns_db_count(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    db_mock.expire_old_invoices.return_value = 3
    svc = _service(db_mock, credits_mock)
    count = await svc.check_and_expire_old_invoices()
    assert count == 3
    db_mock.expire_old_invoices.assert_awaited_once()


async def test_get_invoice_status_passes_through(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    db_mock.get_invoice_by_number.return_value = {"id": "x", "status": "pending"}
    svc = _service(db_mock, credits_mock)
    out = await svc.get_invoice_status("847291-1001")
    assert out is not None
    assert out["status"] == "pending"


async def test_get_invoice_status_returns_none_when_absent(
    db_mock: MagicMock, credits_mock: MagicMock
) -> None:
    db_mock.get_invoice_by_number.return_value = None
    svc = _service(db_mock, credits_mock)
    assert await svc.get_invoice_status("000000-0000") is None
