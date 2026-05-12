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
from packages.platform.config import PlatformConfig
from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient


async def create_bot(
    config: PlatformConfig,
    db: DatabaseClient | None = None,
    credits: CreditLedger | None = None,
) -> tuple[Bot, Dispatcher]:
    """Create and configure the bot and dispatcher.

    Handlers declare ``db: DatabaseClient`` and ``credits: CreditLedger``
    as parameters; aiogram's keyword injection resolves those against
    the dispatcher's ``workflow_data`` dict, so we stash both there
    before returning. The storage class is in-memory for v1 —
    Redis-backed storage is a drop-in replacement and lands when we
    wire up the production deployment.
    """

    bot = Bot(
        token=config.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    resolved_db = db if db is not None else DatabaseClient(config)
    resolved_credits = (
        credits if credits is not None else CreditLedger(resolved_db, dev_mode=config.dev_mode)
    )
    dp["db"] = resolved_db
    dp["credits"] = resolved_credits
    dp["config"] = config

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
) -> None:
    """Run the bot in polling mode (development)."""

    bot, dp = await create_bot(config, db=db, credits=credits)
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

    app.router.add_get("/mini-app/presentation", serve_mini_app)
    return app


async def run_webhook(
    config: PlatformConfig,
    webhook_url: str,
    port: int = 8080,
    db: DatabaseClient | None = None,
    credits: CreditLedger | None = None,
) -> None:
    """Run the bot in webhook mode (production)."""

    from aiohttp import web

    bot, dp = await create_bot(config, db=db, credits=credits)
    await bot.set_webhook(webhook_url)

    app = build_aiohttp_app(bot, dp)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
