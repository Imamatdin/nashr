"""Invoice management for Nashr payments.

An invoice represents a pending payment. Each row carries:

* ``invoice_number`` — the short string the user types into Payme /
  Click / Uzum to find their bill. Generated from the user's
  subscriber ID and the current timestamp.
* ``amount_uzs`` — what the user owes for the selected product tier.
* ``product_type`` — which paid product (``article_basic``,
  ``presentation_premium`` …) the user is paying for; the price comes
  from :data:`CreditLedger.PRICING`.
* ``status`` — ``pending`` while we wait, ``paid`` once a provider
  webhook confirms, ``expired`` after 24 hours, ``cancelled`` if the
  user backs out.

The service owns the lifecycle: create a fresh invoice for the user
(cancelling any prior pending one for that project so we never carry
two live invoices for the same generation), process payment webhooks
idempotently against amount + status, and expire stale invoices.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.platform.credits import CreditLedger
from packages.platform.database import DatabaseClient

logger = logging.getLogger("nashr.invoices")

EXPIRY_HOURS: int = 24


class InvoiceService:
    """Lifecycle manager for payment invoices."""

    def __init__(self, db: DatabaseClient, credits: CreditLedger) -> None:
        self._db = db
        self._credits = credits

    async def create_invoice(
        self,
        user_id: str,
        project_id: str,
        product_type: str,
    ) -> dict[str, Any]:
        """Create a new invoice for a user+project at a product tier.

        If a pending invoice already exists for the same user+project
        pair we expire it first — only one live invoice per generation
        at a time, otherwise the user could end up with two open bills
        for the same article and only paying one would still trigger
        delivery via webhook.
        """

        existing = await self._db.get_pending_invoice(user_id, project_id)
        if existing is not None:
            existing_id = existing.get("id")
            if isinstance(existing_id, str):
                await self._db.mark_invoice_expired(existing_id)

        amount = CreditLedger.PRICING.get(product_type, 0)
        if amount <= 0:
            raise ValueError(f"Unknown product type: {product_type}")

        invoice = await self._db.create_invoice(
            user_id=user_id,
            project_id=project_id,
            amount_uzs=amount,
            product_type=product_type,
        )
        return invoice

    async def process_payment(
        self,
        invoice_number: str,
        payment_provider: str,
        payment_reference: str,
        amount_uzs: int,
    ) -> dict[str, Any]:
        """Process a confirmed payment from a provider webhook.

        Idempotent: a webhook that arrives twice for the same invoice
        returns the existing invoice on the second call without
        double-crediting. Raises :class:`ValueError` if the invoice is
        missing, expired, cancelled, or the amount does not match.
        """

        invoice = await self._db.get_invoice_by_number(invoice_number)
        if invoice is None:
            raise ValueError(f"Invoice not found: {invoice_number}")

        status = invoice.get("status")
        if status == "paid":
            logger.warning(
                "invoice_already_paid",
                extra={"invoice_number": invoice_number, "provider": payment_provider},
            )
            return invoice
        if status == "expired":
            raise ValueError(f"Invoice {invoice_number} has expired")
        if status == "cancelled":
            raise ValueError(f"Invoice {invoice_number} was cancelled")

        expected_amount = int(invoice.get("amount_uzs", 0))
        if amount_uzs != expected_amount:
            raise ValueError(
                f"Amount mismatch for invoice {invoice_number}: "
                f"expected {expected_amount}, got {amount_uzs}"
            )

        invoice_id = invoice.get("id")
        if not isinstance(invoice_id, str):
            raise ValueError(f"Invoice {invoice_number} has no id")
        await self._db.mark_invoice_paid(
            invoice_id=invoice_id,
            payment_provider=payment_provider,
            payment_reference=payment_reference,
        )

        user_id = invoice.get("user_id")
        if not isinstance(user_id, str):
            raise ValueError(f"Invoice {invoice_number} has no user_id")
        await self._credits.grant_paid_credit(
            user_id=user_id,
            amount_uzs=amount_uzs,
            payment_reference=f"{payment_provider}:{payment_reference}",
        )

        logger.info(
            "payment_processed",
            extra={
                "invoice_number": invoice_number,
                "provider": payment_provider,
                "amount_uzs": amount_uzs,
            },
        )

        refreshed = await self._db.get_invoice_by_number(invoice_number)
        return refreshed if refreshed is not None else invoice

    async def check_and_expire_old_invoices(self) -> int:
        """Sweep pending invoices past their 24h expiry.

        Returns the number of invoices that transitioned to ``expired``.
        Wired into a periodic scheduler task; safe to call ad-hoc.
        """

        count = await self._db.expire_old_invoices()
        if count > 0:
            logger.info("invoices_expired", extra={"count": count})
        return count

    async def get_invoice_status(self, invoice_number: str) -> dict[str, Any] | None:
        """Look up an invoice by number; thin pass-through used by webhooks."""

        return await self._db.get_invoice_by_number(invoice_number)

    def generate_deep_link(
        self,
        provider: str,
        invoice_number: str,
        amount_uzs: int,
    ) -> str:
        """Build a deep-link URL that opens the chosen payment app.

        Each provider parses its own URL scheme; Payme wants the amount
        in tiyin (1 UZS = 100 tiyin), Click and Uzum expect plain UZS.
        Returns an empty string for unknown providers so the caller can
        omit the deep-link button cleanly.
        """

        amount_tiyin = amount_uzs * 100

        if provider == "payme":
            return (
                f"https://payme.uz/fallback/merchant/"
                f"?amount={amount_tiyin}"
                f"&account[invoice]={invoice_number}"
            )
        if provider == "click":
            return (
                f"https://my.click.uz/services/pay"
                f"?amount={amount_uzs}"
                f"&transaction_param={invoice_number}"
            )
        if provider == "uzum":
            return f"https://www.uzumbank.uz/pay?amount={amount_uzs}&account={invoice_number}"
        return ""
