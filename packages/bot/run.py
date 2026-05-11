"""CLI entry point for running the Telegram bot in polling mode.

For production deployments use the webhook server in :mod:`app`
behind Caddy; this entry point exists so a fresh checkout can be
booted with ``python -m packages.bot.run`` and a single
``TELEGRAM_BOT_TOKEN`` environment variable.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from packages.bot.app import run_polling
from packages.platform.config import PlatformConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

logger = logging.getLogger("nashr.bot")


def main() -> None:
    """Read config from env and start the polling loop."""

    config = PlatformConfig.from_env()

    if not config.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    logger.info("Starting Nashr bot in polling mode...")
    asyncio.run(run_polling(config))


if __name__ == "__main__":
    main()
