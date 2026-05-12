"""HTTP webhook handlers mounted on the bot's aiohttp app.

Currently exposes :mod:`packages.bot.webhooks.payment_webhooks`, which
registers ``/webhooks/payme``, ``/webhooks/click``, ``/webhooks/uzum``,
and ``/api/invoices/{invoice_number}`` on the same aiohttp web server
that serves Telegram webhook updates and the Mini App static files.
"""
