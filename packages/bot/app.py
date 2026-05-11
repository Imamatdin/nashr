"""Telegram bot application factory.

Builds the :class:`Bot` and :class:`Dispatcher` instances, attaches
the shared :class:`DatabaseClient` so handlers can receive it via
keyword injection, and registers every router from
:mod:`packages.bot.handlers`. Two entry points are provided: polling
for local development and a webhook server for production.
"""

from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

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
    resolved_credits = credits if credits is not None else CreditLedger(resolved_db)
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


async def run_webhook(
    config: PlatformConfig,
    webhook_url: str,
    port: int = 8080,
    db: DatabaseClient | None = None,
    credits: CreditLedger | None = None,
) -> None:
    """Run the bot in webhook mode (production)."""

    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from aiohttp import web

    bot, dp = await create_bot(config, db=db, credits=credits)
    await bot.set_webhook(webhook_url)

    app = web.Application()
    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
