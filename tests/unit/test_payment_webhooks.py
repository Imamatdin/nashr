"""Behaviour tests for payment-provider webhook handlers.

Each test boots a fresh :class:`aiohttp.web.Application`, registers the
payment routes via :func:`register_payment_webhooks` with a spec'd
:class:`InvoiceService` mock, then drives a real HTTP request through
:class:`aiohttp.test_utils.TestClient`. This exercises the actual
aiohttp request/response path — content negotiation, JSON parsing,
route dispatch — rather than the bare handler functions, which is what
production traffic sees.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

from aiogram import Bot
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from packages.bot.webhooks.payment_webhooks import register_payment_webhooks
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.invoices import InvoiceService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _config(payme_key: str = "", click_key: str = "") -> PlatformConfig:
    return PlatformConfig(
        supabase_url="https://test.supabase.co",
        supabase_service_key="test-service-key",
        telegram_bot_token="test-token",
        payme_merchant_id="merchant_x" if payme_key else "",
        payme_secret_key=payme_key,
        click_merchant_id="click_m" if click_key else "",
        click_secret_key=click_key,
    )


def _invoice_service_mock() -> MagicMock:
    mock = MagicMock(spec=InvoiceService)
    mock.get_invoice_status = AsyncMock(return_value=None)
    mock.process_payment = AsyncMock(return_value={})
    mock.create_invoice = AsyncMock(return_value={})
    mock.check_and_expire_old_invoices = AsyncMock(return_value=0)
    return mock


def _db_mock() -> MagicMock:
    mock = MagicMock(spec=DatabaseClient)
    mock.get_user_by_id = AsyncMock(return_value=None)
    return mock


def _bot_mock() -> MagicMock:
    mock = MagicMock(spec=Bot)
    mock.send_message = AsyncMock(return_value=None)
    return mock


async def _build_client(
    *,
    invoice_service: MagicMock,
    db: MagicMock,
    config: PlatformConfig,
    bot: MagicMock,
) -> TestClient:
    app = web.Application()
    register_payment_webhooks(
        app,
        cast(Any, invoice_service),
        cast(Any, db),
        config,
        cast(Any, bot),
    )
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    return client


def _pending_invoice(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "inv1",
        "invoice_number": "847291-1001",
        "user_id": "u1",
        "amount_uzs": 60_000,
        "product_type": "article_basic",
        "status": "pending",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Payme — CheckPerformTransaction
# ---------------------------------------------------------------------------


async def test_payme_check_perform_valid_invoice_returns_allow() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice()
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "CheckPerformTransaction",
                "params": {
                    "amount": 6_000_000,
                    "account": {"invoice": "847291-1001"},
                },
                "id": 1,
            },
        )
        body = await resp.json()
        assert resp.status == 200
        assert body["result"] == {"allow": True}
        assert body["id"] == 1
    finally:
        await client.close()


async def test_payme_check_perform_invoice_missing_returns_31050() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = None
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "CheckPerformTransaction",
                "params": {"amount": 6_000_000, "account": {"invoice": "missing"}},
                "id": 7,
            },
        )
        body = await resp.json()
        assert body["error"]["code"] == -31050
        assert body["id"] == 7
    finally:
        await client.close()


async def test_payme_check_perform_amount_mismatch_returns_31001() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice(amount_uzs=60_000)
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "CheckPerformTransaction",
                "params": {"amount": 5_000_000, "account": {"invoice": "847291-1001"}},
                "id": 9,
            },
        )
        body = await resp.json()
        assert body["error"]["code"] == -31001
    finally:
        await client.close()


async def test_payme_check_perform_inactive_returns_31051() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice(status="paid")
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "CheckPerformTransaction",
                "params": {"amount": 6_000_000, "account": {"invoice": "847291-1001"}},
                "id": 11,
            },
        )
        body = await resp.json()
        assert body["error"]["code"] == -31051
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Payme — PerformTransaction
# ---------------------------------------------------------------------------


async def test_payme_perform_transaction_processes_payment_and_notifies() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.process_payment.return_value = _pending_invoice(status="paid")
    db = _db_mock()
    db.get_user_by_id.return_value = {"id": "u1", "telegram_id": 555, "language": "uz"}
    bot = _bot_mock()
    client = await _build_client(invoice_service=invoice_service, db=db, config=_config(), bot=bot)
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "PerformTransaction",
                "params": {
                    "amount": 6_000_000,
                    "account": {"invoice": "847291-1001"},
                    "id": "PAYME-TX-1",
                },
                "id": 21,
            },
        )
        body = await resp.json()
    finally:
        await client.close()

    assert body["result"]["state"] == 2
    invoice_service.process_payment.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    chat_id = bot.send_message.await_args.kwargs.get("chat_id")
    assert chat_id == 555


async def test_payme_perform_transaction_failed_returns_31008() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.process_payment.side_effect = ValueError("Invoice expired")
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "PerformTransaction",
                "params": {
                    "amount": 6_000_000,
                    "account": {"invoice": "847291-1001"},
                    "id": "PAYME-TX-2",
                },
                "id": 22,
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"]["code"] == -31008
    assert "expired" in body["error"]["message"]


# ---------------------------------------------------------------------------
# Payme auth
# ---------------------------------------------------------------------------


async def test_payme_auth_rejects_when_credentials_configured_and_header_missing() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice()
    config = _config(payme_key="secret123")
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=config, bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "CheckPerformTransaction",
                "params": {"amount": 6_000_000, "account": {"invoice": "847291-1001"}},
                "id": 1,
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"]["code"] == -32504


async def test_payme_auth_accepts_correct_basic_header() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice()
    config = _config(payme_key="secret123")
    creds = base64.b64encode(b"merchant_x:secret123").decode("ascii")
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=config, bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "CheckPerformTransaction",
                "params": {"amount": 6_000_000, "account": {"invoice": "847291-1001"}},
                "id": 1,
            },
            headers={"Authorization": f"Basic {creds}"},
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["result"] == {"allow": True}


async def test_payme_unknown_method_returns_32601() -> None:
    invoice_service = _invoice_service_mock()
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={"method": "NoSuchMethod", "params": {}, "id": 99},
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# Click — prepare (action=0)
# ---------------------------------------------------------------------------


async def test_click_prepare_valid_invoice_returns_zero() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice()
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/click",
            data={
                "action": "0",
                "click_trans_id": "CT-1",
                "merchant_trans_id": "847291-1001",
                "amount": "60000",
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"] == 0
    assert body["merchant_trans_id"] == "847291-1001"


async def test_click_prepare_invoice_missing_returns_minus_five() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = None
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/click",
            data={
                "action": "0",
                "click_trans_id": "CT-2",
                "merchant_trans_id": "missing",
                "amount": "60000",
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"] == -5


async def test_click_prepare_amount_mismatch_returns_minus_two() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice(amount_uzs=60_000)
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/click",
            data={
                "action": "0",
                "click_trans_id": "CT-3",
                "merchant_trans_id": "847291-1001",
                "amount": "50000",
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"] == -2


# ---------------------------------------------------------------------------
# Click — complete (action=1)
# ---------------------------------------------------------------------------


async def test_click_complete_processes_payment_and_notifies() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.process_payment.return_value = _pending_invoice(status="paid")
    db = _db_mock()
    db.get_user_by_id.return_value = {"id": "u1", "telegram_id": 777, "language": "uz"}
    bot = _bot_mock()
    client = await _build_client(invoice_service=invoice_service, db=db, config=_config(), bot=bot)
    try:
        resp = await client.post(
            "/webhooks/click",
            data={
                "action": "1",
                "click_trans_id": "CT-4",
                "merchant_trans_id": "847291-1001",
                "amount": "60000",
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"] == 0
    invoice_service.process_payment.assert_awaited_once()
    bot.send_message.assert_awaited_once()


async def test_click_complete_process_failure_returns_minus_nine() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.process_payment.side_effect = ValueError("expired")
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/click",
            data={
                "action": "1",
                "click_trans_id": "CT-5",
                "merchant_trans_id": "847291-1001",
                "amount": "60000",
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"] == -9


async def test_click_signature_verification_rejects_bad_sign() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice()
    config = _config(click_key="click_secret")
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=config, bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/click",
            data={
                "action": "0",
                "click_trans_id": "CT-6",
                "merchant_trans_id": "847291-1001",
                "amount": "60000",
                "service_id": "svc",
                "sign_time": "2026-05-11 10:00:00",
                "sign_string": "deadbeef",
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"] == -1


async def test_click_signature_verification_accepts_correct_sign() -> None:
    secret = "click_secret"
    fields: dict[str, str] = {
        "action": "0",
        "click_trans_id": "CT-7",
        "merchant_trans_id": "847291-1001",
        "amount": "60000",
        "service_id": "svc",
        "sign_time": "2026-05-11 10:00:00",
    }
    sign_input = (
        fields["click_trans_id"]
        + fields["service_id"]
        + secret
        + fields["merchant_trans_id"]
        + fields["amount"]
        + fields["action"]
        + fields["sign_time"]
    )
    expected_sign = hashlib.md5(sign_input.encode("utf-8")).hexdigest()
    fields["sign_string"] = expected_sign

    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice()
    config = _config(click_key=secret)
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=config, bot=_bot_mock()
    )
    try:
        resp = await client.post("/webhooks/click", data=fields)
        body = await resp.json()
    finally:
        await client.close()
    assert body["error"] == 0


# ---------------------------------------------------------------------------
# Uzum
# ---------------------------------------------------------------------------


async def test_uzum_webhook_processes_when_fields_present() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.process_payment.return_value = _pending_invoice(status="paid")
    db = _db_mock()
    db.get_user_by_id.return_value = {"id": "u1", "telegram_id": 333, "language": "uz"}
    bot = _bot_mock()
    client = await _build_client(invoice_service=invoice_service, db=db, config=_config(), bot=bot)
    try:
        resp = await client.post(
            "/webhooks/uzum",
            json={
                "account": "847291-1001",
                "amount": 60_000,
                "transaction_id": "UZUM-TX-1",
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body == {"status": "ok"}
    invoice_service.process_payment.assert_awaited_once()
    bot.send_message.assert_awaited_once()


async def test_uzum_webhook_logs_unknown_format_without_processing() -> None:
    invoice_service = _invoice_service_mock()
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post("/webhooks/uzum", json={"unrelated": "fields"})
        body = await resp.json()
    finally:
        await client.close()
    assert body == {"status": "received"}
    invoice_service.process_payment.assert_not_called()


async def test_uzum_webhook_reports_process_error() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.process_payment.side_effect = ValueError("Amount mismatch")
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/uzum",
            json={"account": "847291-1001", "amount": 50_000, "transaction_id": "UZUM-2"},
        )
        body = await resp.json()
    finally:
        await client.close()
    assert resp.status == 400
    assert body["status"] == "error"


# ---------------------------------------------------------------------------
# Invoice lookup endpoint
# ---------------------------------------------------------------------------


async def test_invoice_lookup_returns_record_when_present() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = _pending_invoice()
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.get("/api/invoices/847291-1001")
        body = await resp.json()
    finally:
        await client.close()
    assert resp.status == 200
    assert body["invoice_number"] == "847291-1001"
    assert body["amount_uzs"] == 60_000
    assert body["status"] == "pending"


async def test_invoice_lookup_returns_404_when_absent() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.get_invoice_status.return_value = None
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.get("/api/invoices/missing-0000")
    finally:
        await client.close()
    assert resp.status == 404


# ---------------------------------------------------------------------------
# Payme — invalid JSON
# ---------------------------------------------------------------------------


async def test_payme_invalid_json_returns_400() -> None:
    invoice_service = _invoice_service_mock()
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            data="not-json",
            headers={"Content-Type": "application/json"},
        )
    finally:
        await client.close()
    assert resp.status == 400


# ---------------------------------------------------------------------------
# Payme — Create / Cancel transactions return acknowledgments
# ---------------------------------------------------------------------------


async def test_payme_create_transaction_returns_state_one() -> None:
    invoice_service = _invoice_service_mock()
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "CreateTransaction",
                "params": {"id": "TX-A", "amount": 6_000_000},
                "id": 3,
            },
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["result"]["state"] == 1
    assert body["result"]["transaction"] == "TX-A"


async def test_payme_cancel_transaction_returns_state_negative_one() -> None:
    invoice_service = _invoice_service_mock()
    client = await _build_client(
        invoice_service=invoice_service, db=_db_mock(), config=_config(), bot=_bot_mock()
    )
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={"method": "CancelTransaction", "params": {"id": "TX-B"}, "id": 4},
        )
        body = await resp.json()
    finally:
        await client.close()
    assert body["result"]["state"] == -1


# ---------------------------------------------------------------------------
# Notification skipped when telegram_id missing
# ---------------------------------------------------------------------------


async def test_payment_notification_skipped_when_user_missing() -> None:
    invoice_service = _invoice_service_mock()
    invoice_service.process_payment.return_value = _pending_invoice(status="paid")
    db = _db_mock()
    db.get_user_by_id.return_value = None
    bot = _bot_mock()
    client = await _build_client(invoice_service=invoice_service, db=db, config=_config(), bot=bot)
    try:
        resp = await client.post(
            "/webhooks/payme",
            json={
                "method": "PerformTransaction",
                "params": {
                    "amount": 6_000_000,
                    "account": {"invoice": "847291-1001"},
                    "id": "TX-Z",
                },
                "id": 50,
            },
        )
        await resp.json()
    finally:
        await client.close()
    bot.send_message.assert_not_called()
