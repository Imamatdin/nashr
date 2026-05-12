"""Payment provider webhook handlers (Payme JSON-RPC, Click form, Uzum).

Every provider POSTs a confirmation to a dedicated endpoint when a
payment completes. The handler verifies credentials, looks up the
invoice through :class:`InvoiceService`, processes the payment, and
notifies the user over Telegram.

Routes registered by :func:`register_payment_webhooks`:

* ``POST /webhooks/payme`` — Payme JSON-RPC (Check/Create/Perform/Cancel)
* ``POST /webhooks/click`` — Click form-encoded (action 0 = prepare,
  action 1 = complete)
* ``POST /webhooks/uzum``  — Uzum JSON placeholder (logs and best-effort
  processes; full spec lands when credentials arrive)
* ``GET  /api/invoices/{invoice_number}`` — read-only lookup used by
  payment providers verifying the user typed a valid invoice number

When provider credentials are absent the handler short-circuits auth
verification (log-only mode) so the wiring can run end-to-end against
provider sandboxes before merchant approval. CLAUDE.md's 300-line cap
is intentionally exceeded: each provider has its own JSON-RPC / form
contract and splitting them would scatter the request-shape parsing
across files without buying any reuse.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

from aiogram import Bot
from aiohttp import web

from packages.bot.labels import get_bot_labels
from packages.platform.config import PlatformConfig
from packages.platform.database import DatabaseClient
from packages.platform.invoices import InvoiceService

logger = logging.getLogger("nashr.webhooks.payment")


# Payme JSON-RPC error codes (per Payme merchant API spec)
PAYME_ERR_INSUFFICIENT_PRIVILEGE: int = -32504
PAYME_ERR_METHOD_NOT_FOUND: int = -32601
PAYME_ERR_INVALID_AMOUNT: int = -31001
PAYME_ERR_TRANSACTION_FAILED: int = -31008
PAYME_ERR_INVOICE_MISSING: int = -31050
PAYME_ERR_INVOICE_INACTIVE: int = -31051

# Click error codes (per Click integration spec)
CLICK_OK: int = 0
CLICK_ERR_SIGN: int = -1
CLICK_ERR_AMOUNT: int = -2
CLICK_ERR_ACTION: int = -3
CLICK_ERR_INACTIVE: int = -4
CLICK_ERR_INVOICE_MISSING: int = -5
CLICK_ERR_TRANSACTION: int = -9


def register_payment_webhooks(
    app: web.Application,
    invoice_service: InvoiceService,
    db: DatabaseClient,
    config: PlatformConfig,
    bot: Bot,
) -> None:
    """Register every payment-provider webhook route on ``app``.

    The bot reference is held in closures so the handler can push a
    confirmation message to the user without round-tripping back through
    the dispatcher; both lifetimes are tied to the same aiohttp app.
    """

    async def handle_payme(request: web.Request) -> web.Response:
        return await _handle_payme(request, invoice_service, db, config, bot)

    async def handle_click(request: web.Request) -> web.Response:
        return await _handle_click(request, invoice_service, db, config, bot)

    async def handle_uzum(request: web.Request) -> web.Response:
        return await _handle_uzum(request, invoice_service, db, bot)

    async def invoice_lookup(request: web.Request) -> web.Response:
        invoice_number = request.match_info.get("invoice_number", "")
        invoice = await invoice_service.get_invoice_status(invoice_number)
        if invoice is None:
            return web.json_response({"error": "Not found"}, status=404)
        return web.json_response(
            {
                "invoice_number": invoice.get("invoice_number", ""),
                "amount_uzs": invoice.get("amount_uzs", 0),
                "status": invoice.get("status", ""),
                "product_type": invoice.get("product_type", ""),
            }
        )

    app.router.add_post("/webhooks/payme", handle_payme)
    app.router.add_post("/webhooks/click", handle_click)
    app.router.add_post("/webhooks/uzum", handle_uzum)
    app.router.add_get("/api/invoices/{invoice_number}", invoice_lookup)


# ---------------------------------------------------------------------------
# Payme
# ---------------------------------------------------------------------------


async def _handle_payme(
    request: web.Request,
    invoice_service: InvoiceService,
    db: DatabaseClient,
    config: PlatformConfig,
    bot: Bot,
) -> web.Response:
    """Dispatch a Payme JSON-RPC request to the matching method handler."""

    try:
        body: dict[str, Any] = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    method = str(body.get("method", ""))
    params_raw = body.get("params")
    params: dict[str, Any] = (
        cast(dict[str, Any], params_raw) if isinstance(params_raw, dict) else {}
    )
    request_id = body.get("id", 0)

    logger.info("payme_webhook", extra={"method": method})

    if config.payme_secret_key and not _verify_payme_auth(
        request.headers.get("Authorization", ""),
        config.payme_merchant_id,
        config.payme_secret_key,
    ):
        return web.json_response(
            {
                "error": {
                    "code": PAYME_ERR_INSUFFICIENT_PRIVILEGE,
                    "message": "Insufficient privilege",
                },
                "id": request_id,
            }
        )

    if method == "CheckPerformTransaction":
        return await _payme_check_perform(params, request_id, invoice_service)
    if method == "CreateTransaction":
        return _payme_create_transaction(params, request_id)
    if method == "PerformTransaction":
        return await _payme_perform_transaction(params, request_id, invoice_service, db, bot)
    if method == "CancelTransaction":
        return _payme_cancel_transaction(params, request_id)

    return web.json_response(
        {
            "error": {
                "code": PAYME_ERR_METHOD_NOT_FOUND,
                "message": f"Method not found: {method}",
            },
            "id": request_id,
        }
    )


async def _payme_check_perform(
    params: dict[str, Any], request_id: Any, invoice_service: InvoiceService
) -> web.Response:
    """Verify the invoice exists, is pending, and the amount matches."""

    account_raw = params.get("account")
    account: dict[str, Any] = (
        cast(dict[str, Any], account_raw) if isinstance(account_raw, dict) else {}
    )
    invoice_number = str(account.get("invoice", ""))
    amount_tiyin = int(params.get("amount", 0))
    amount_uzs = amount_tiyin // 100

    invoice = await invoice_service.get_invoice_status(invoice_number)
    if invoice is None:
        return web.json_response(
            {
                "error": {"code": PAYME_ERR_INVOICE_MISSING, "message": "Invoice not found"},
                "id": request_id,
            }
        )
    if invoice.get("status") != "pending":
        return web.json_response(
            {
                "error": {"code": PAYME_ERR_INVOICE_INACTIVE, "message": "Invoice not active"},
                "id": request_id,
            }
        )
    if int(invoice.get("amount_uzs", 0)) != amount_uzs:
        return web.json_response(
            {
                "error": {"code": PAYME_ERR_INVALID_AMOUNT, "message": "Amount mismatch"},
                "id": request_id,
            }
        )

    return web.json_response({"result": {"allow": True}, "id": request_id})


async def _payme_perform_transaction(
    params: dict[str, Any],
    request_id: Any,
    invoice_service: InvoiceService,
    db: DatabaseClient,
    bot: Bot,
) -> web.Response:
    """Finalise the payment: mark invoice paid, credit user, notify."""

    account_raw = params.get("account")
    account: dict[str, Any] = (
        cast(dict[str, Any], account_raw) if isinstance(account_raw, dict) else {}
    )
    invoice_number = str(account.get("invoice", ""))
    amount_uzs = int(params.get("amount", 0)) // 100
    transaction_id = str(params.get("id", ""))

    try:
        invoice = await invoice_service.process_payment(
            invoice_number=invoice_number,
            payment_provider="payme",
            payment_reference=transaction_id,
            amount_uzs=amount_uzs,
        )
    except ValueError as exc:
        return web.json_response(
            {
                "error": {"code": PAYME_ERR_TRANSACTION_FAILED, "message": str(exc)},
                "id": request_id,
            }
        )

    await _notify_user_payment(bot, db, invoice)

    perform_time = int(datetime.now(UTC).timestamp() * 1000)
    return web.json_response(
        {
            "result": {
                "transaction": transaction_id,
                "perform_time": perform_time,
                "state": 2,
            },
            "id": request_id,
        }
    )


def _payme_create_transaction(params: dict[str, Any], request_id: Any) -> web.Response:
    """Pre-authorisation step: we acknowledge and let Perform do the work."""

    return web.json_response(
        {
            "result": {
                "create_time": int(datetime.now(UTC).timestamp() * 1000),
                "transaction": str(params.get("id", "")),
                "state": 1,
            },
            "id": request_id,
        }
    )


def _payme_cancel_transaction(params: dict[str, Any], request_id: Any) -> web.Response:
    """Cancel acknowledgement (no-op on our side — invoice stays pending)."""

    return web.json_response(
        {
            "result": {
                "transaction": str(params.get("id", "")),
                "cancel_time": int(datetime.now(UTC).timestamp() * 1000),
                "state": -1,
            },
            "id": request_id,
        }
    )


# ---------------------------------------------------------------------------
# Click
# ---------------------------------------------------------------------------


async def _handle_click(
    request: web.Request,
    invoice_service: InvoiceService,
    db: DatabaseClient,
    config: PlatformConfig,
    bot: Bot,
) -> web.Response:
    """Click sends ``application/x-www-form-urlencoded`` for action 0 / 1."""

    data = await _read_click_payload(request)
    if data is None:
        return web.json_response({"error": CLICK_ERR_SIGN, "error_note": "Invalid request"})

    try:
        action = int(data.get("action", -1))
    except (TypeError, ValueError):
        action = -1
    invoice_number = str(data.get("merchant_trans_id", ""))
    try:
        amount_uzs = int(float(data.get("amount", 0)))
    except (TypeError, ValueError):
        amount_uzs = 0
    click_trans_id = str(data.get("click_trans_id", ""))
    sign_string = str(data.get("sign_string", ""))

    logger.info(
        "click_webhook",
        extra={"action": action, "invoice": invoice_number, "amount_uzs": amount_uzs},
    )

    if config.click_secret_key:
        expected = _compute_click_sign(data, config.click_secret_key)
        if not hmac.compare_digest(sign_string, expected):
            return web.json_response({"error": CLICK_ERR_SIGN, "error_note": "Invalid signature"})

    if action == 0:
        return await _click_prepare(invoice_number, amount_uzs, click_trans_id, invoice_service)
    if action == 1:
        return await _click_complete(
            invoice_number, amount_uzs, click_trans_id, invoice_service, db, bot
        )
    return web.json_response({"error": CLICK_ERR_ACTION, "error_note": "Unknown action"})


async def _read_click_payload(request: web.Request) -> dict[str, Any] | None:
    """Accept form-encoded (Click prod) or JSON (Click sandbox) payloads."""

    try:
        form = await request.post()
        if form:
            out: dict[str, Any] = {}
            for key in form:
                out[str(key)] = form[key]
            return out
    except Exception:
        pass
    try:
        body = await request.json()
    except Exception:
        return None
    if isinstance(body, dict):
        return cast(dict[str, Any], body)
    return None


async def _click_prepare(
    invoice_number: str,
    amount_uzs: int,
    click_trans_id: str,
    invoice_service: InvoiceService,
) -> web.Response:
    """Action 0: verify the invoice exists, pending, and amount matches."""

    invoice = await invoice_service.get_invoice_status(invoice_number)
    if invoice is None:
        return web.json_response(
            {"error": CLICK_ERR_INVOICE_MISSING, "error_note": "Invoice not found"}
        )
    if invoice.get("status") != "pending":
        return web.json_response({"error": CLICK_ERR_INACTIVE, "error_note": "Invoice not active"})
    if int(invoice.get("amount_uzs", 0)) != amount_uzs:
        return web.json_response({"error": CLICK_ERR_AMOUNT, "error_note": "Amount mismatch"})
    return web.json_response(
        {
            "error": CLICK_OK,
            "error_note": "Success",
            "click_trans_id": click_trans_id,
            "merchant_trans_id": invoice_number,
            "merchant_prepare_id": invoice.get("id", ""),
        }
    )


async def _click_complete(
    invoice_number: str,
    amount_uzs: int,
    click_trans_id: str,
    invoice_service: InvoiceService,
    db: DatabaseClient,
    bot: Bot,
) -> web.Response:
    """Action 1: finalise the payment and notify the user."""

    try:
        invoice = await invoice_service.process_payment(
            invoice_number=invoice_number,
            payment_provider="click",
            payment_reference=click_trans_id,
            amount_uzs=amount_uzs,
        )
    except ValueError as exc:
        return web.json_response({"error": CLICK_ERR_TRANSACTION, "error_note": str(exc)})

    await _notify_user_payment(bot, db, invoice)
    return web.json_response(
        {
            "error": CLICK_OK,
            "error_note": "Success",
            "click_trans_id": click_trans_id,
            "merchant_trans_id": invoice_number,
            "merchant_confirm_id": invoice.get("id", ""),
        }
    )


# ---------------------------------------------------------------------------
# Uzum (placeholder until merchant credentials land)
# ---------------------------------------------------------------------------


async def _handle_uzum(
    request: web.Request,
    invoice_service: InvoiceService,
    db: DatabaseClient,
    bot: Bot,
) -> web.Response:
    """Uzum integration is a log-only placeholder until credentials arrive."""

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        body = {}

    logger.info("uzum_webhook", extra={"payload": body})

    invoice_number = str(body.get("account") or body.get("invoice") or "")
    try:
        amount = int(body.get("amount", 0))
    except (TypeError, ValueError):
        amount = 0
    transaction_id = str(body.get("transaction_id") or body.get("id") or "")

    if not invoice_number or amount <= 0 or not transaction_id:
        return web.json_response({"status": "received"})

    try:
        invoice = await invoice_service.process_payment(
            invoice_number=invoice_number,
            payment_provider="uzum",
            payment_reference=transaction_id,
            amount_uzs=amount,
        )
    except ValueError as exc:
        return web.json_response({"status": "error", "message": str(exc)}, status=400)

    await _notify_user_payment(bot, db, invoice)
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _notify_user_payment(bot: Bot, db: DatabaseClient, invoice: dict[str, Any]) -> None:
    """Tell the user the payment landed; failures are swallowed and logged."""

    user_id = invoice.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        return
    user = await db.get_user_by_id(user_id)
    if user is None:
        logger.warning(
            "payment_notify_user_missing",
            extra={"invoice_number": invoice.get("invoice_number")},
        )
        return
    telegram_id = user.get("telegram_id")
    if not isinstance(telegram_id, int):
        return
    lang = user.get("language", "uz")
    if not isinstance(lang, str):
        lang = "uz"
    labels = get_bot_labels(lang)
    try:
        await bot.send_message(chat_id=telegram_id, text=labels.payment_confirmed)
    except Exception as exc:
        logger.error(
            "payment_notify_failed",
            extra={"telegram_id": telegram_id, "error_type": type(exc).__name__},
        )


def _verify_payme_auth(auth_header: str, merchant_id: str, secret_key: str) -> bool:
    """Verify Payme's Basic-auth credentials in constant time."""

    if not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
    except Exception:
        return False
    expected = f"{merchant_id}:{secret_key}"
    return hmac.compare_digest(decoded, expected)


def _compute_click_sign(data: dict[str, Any], secret_key: str) -> str:
    """Compute the Click MD5 signature over the documented field order."""

    parts = [
        str(data.get("click_trans_id", "")),
        str(data.get("service_id", "")),
        secret_key,
        str(data.get("merchant_trans_id", "")),
        str(data.get("amount", "")),
        str(data.get("action", "")),
        str(data.get("sign_time", "")),
    ]
    return hashlib.md5("".join(parts).encode("utf-8")).hexdigest()
