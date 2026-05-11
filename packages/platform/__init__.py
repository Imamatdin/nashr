"""Platform services: database client, credit ledger, payments, bot utilities.

The platform package wraps the cross-cutting infrastructure that every
worker and the Telegram bot share: Supabase persistence, the append-only
credit ledger, invoice issuance, and (later) payment-provider clients.
"""
