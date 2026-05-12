"""CLI entry point for running the Telegram bot.

Two modes:

  * Polling (default, development) — ``python -m packages.bot.run``
  * Webhook (production)           — ``python -m packages.bot.run --webhook``

Webhook mode reads :attr:`PlatformConfig.webhook_url` from the
``WEBHOOK_URL`` env var and listens on ``--port`` (default 8080),
exposing ``/webhook`` for Telegram updates, ``/health`` for Docker
probes, and the Mini-App + payment webhook routes.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from packages.platform.config import PlatformConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("nashr.bot")


def main() -> None:
    """Parse CLI args, validate config, and start the chosen mode."""

    parser = argparse.ArgumentParser(description="Nashr Telegram bot")
    parser.add_argument(
        "--webhook",
        action="store_true",
        help="Run in webhook mode (requires WEBHOOK_URL env var)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Webhook server port (default: WEBHOOK_PORT env var or 8080)",
    )
    args = parser.parse_args()

    config = PlatformConfig.from_env()

    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    if args.webhook:
        webhook_url = config.webhook_url
        if not webhook_url:
            logger.error("WEBHOOK_URL not set (required for webhook mode)")
            sys.exit(1)

        port = args.port if args.port is not None else config.webhook_port
        logger.info("Starting Nashr bot in webhook mode on port %d...", port)
        asyncio.run(_run_webhook_forever(config, webhook_url, port))
    else:
        if config.dev_mode:
            logger.info("Starting Nashr bot in polling mode (DEV MODE)...")
        else:
            logger.info("Starting Nashr bot in polling mode...")
        from packages.bot.app import run_polling

        asyncio.run(run_polling(config))


async def _run_webhook_forever(config: PlatformConfig, url: str, port: int) -> None:
    """Start the webhook listener and block the event loop indefinitely.

    :func:`run_webhook` returns once the aiohttp listener is up; on its
    own the process would exit. We hold an unset :class:`asyncio.Event`
    open so the bot keeps serving requests until the container receives
    SIGTERM or a KeyboardInterrupt.
    """

    from packages.bot.app import run_webhook

    await run_webhook(config, url, port=port)
    await asyncio.Event().wait()


if __name__ == "__main__":
    main()
