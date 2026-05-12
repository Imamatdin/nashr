"""Telegram bot application factory.

Builds the :class:`Bot` and :class:`Dispatcher` instances, attaches
the shared :class:`DatabaseClient` so handlers can receive it via
keyword injection, and registers every router from
:mod:`packages.bot.handlers`. Two entry points are provided: polling
for local development and a webhook server for production.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

if TYPE_CHECKING:
    from aiohttp import web

from packages.bot.handlers import (
    article_flow,
    common,
    main_menu,
    payment_flow,
    presentation_flow,
    registration,
)
from packages.bot.middleware import InputValidationMiddleware, RateLimitMiddleware
from packages.bot.webhooks.payment_webhooks import register_payment_webhooks
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient
from packages.platform.invoices import InvoiceService
from packages.platform.storage import FileStorage


async def create_bot(
    config: PlatformConfig,
    db: DatabaseClient | None = None,
    credits: CreditLedger | None = None,
    storage: FileStorage | None = None,
) -> tuple[Bot, Dispatcher]:
    """Create and configure the bot and dispatcher.

    Handlers declare ``db: DatabaseClient`` and ``credits: CreditLedger``
    as parameters; aiogram's keyword injection resolves those against
    the dispatcher's ``workflow_data`` dict, so we stash both there
    before returning. The FSM storage is in-memory for v1 — Redis-backed
    storage is a drop-in replacement and lands with the production
    deployment. ``storage`` is the R2 client; when omitted a fresh
    :class:`FileStorage` is built from ``config`` (which gracefully
    degrades to local-disk fallback without R2 credentials).
    """

    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    fsm_storage = MemoryStorage()
    dp = Dispatcher(storage=fsm_storage)

    resolved_db = db if db is not None else DatabaseClient(config)
    resolved_credits = (
        credits if credits is not None else CreditLedger(resolved_db, dev_mode=config.dev_mode)
    )
    resolved_storage = storage if storage is not None else FileStorage(config)
    dp["db"] = resolved_db
    dp["credits"] = resolved_credits
    dp["config"] = config
    dp["storage"] = resolved_storage

    rate_limiter = RateLimitMiddleware()
    input_validator = InputValidationMiddleware()
    dp.message.middleware(input_validator)
    dp.callback_query.middleware(input_validator)
    dp.message.middleware(rate_limiter)
    dp.callback_query.middleware(rate_limiter)

    dp.include_router(common.router)
    dp.include_router(registration.router)
    dp.include_router(main_menu.router)
    dp.include_router(article_flow.router)
    dp.include_router(presentation_flow.router)
    dp.include_router(payment_flow.router)

    return bot, dp


async def run_polling(
    config: PlatformConfig,
    db: DatabaseClient | None = None,
    credits: CreditLedger | None = None,
    storage: FileStorage | None = None,
) -> None:
    """Run the bot in polling mode (development)."""

    bot, dp = await create_bot(config, db=db, credits=credits, storage=storage)
    await dp.start_polling(bot)  # pyright: ignore[reportUnknownMemberType]


MINI_APP_HTML_PATH: Path = Path(__file__).parent / "mini_app" / "presentation_questionnaire.html"


def build_aiohttp_app(
    bot: Bot,
    dp: Dispatcher,
    *,
    mini_app_path: Path = MINI_APP_HTML_PATH,
) -> web.Application:
    """Construct the aiohttp app that wraps the webhook and Mini App routes.

    Split from :func:`run_webhook` so tests can exercise the static-file
    serving without spinning up a TCP listener or contacting Telegram.
    Payment webhook routes (``/webhooks/payme``, ``/webhooks/click``,
    ``/webhooks/uzum``, ``/api/invoices/{number}``) are registered when
    the dispatcher carries ``db``, ``credits``, and ``config`` keys —
    the production startup path always does; tests that only need the
    Telegram webhook plumbing can omit them.
    """

    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from aiohttp import web

    app = web.Application()
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    async def serve_mini_app(_: web.Request) -> web.Response:
        html = mini_app_path.read_text(encoding="utf-8")
        return web.Response(text=html, content_type="text/html")

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "nashr-bot", "version": "1.0.0"})

    app.router.add_get("/mini-app/presentation", serve_mini_app)
    app.router.add_get("/health", health)

    db = dp.workflow_data.get("db")
    credits_ledger = dp.workflow_data.get("credits")
    config = dp.workflow_data.get("config")
    if (
        isinstance(db, DatabaseClient)
        and isinstance(credits_ledger, CreditLedger)
        and isinstance(config, PlatformConfig)
    ):
        invoice_service = InvoiceService(db, credits_ledger)
        register_payment_webhooks(app, invoice_service, db, config, bot)
    return app


async def run_webhook(
    config: PlatformConfig,
    webhook_url: str,
    port: int = 8080,
    db: DatabaseClient | None = None,
    credits: CreditLedger | None = None,
    storage: FileStorage | None = None,
) -> None:
    """Run the bot in webhook mode (production).

    Sets the Telegram webhook URL and starts an aiohttp listener on
    ``0.0.0.0:port`` exposing ``/webhook`` (Telegram updates),
    ``/health`` (Docker / load-balancer probes), ``/mini-app/*``, and
    the payment provider webhooks. The coroutine returns once the
    server is up; callers keep the event loop alive (``asyncio.run``
    or an outer ``Event.wait()``).
    """

    from aiohttp import web

    bot, dp = await create_bot(config, db=db, credits=credits, storage=storage)
    await bot.set_webhook(webhook_url)

    app = build_aiohttp_app(bot, dp)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
