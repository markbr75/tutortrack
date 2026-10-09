# ADR 0008: Connected provider accounts, a provider interface and routed webhooks

- **Status:** Accepted
- **Date:** 2026-10-09
- **Epic:** E11

## Context
Tenants take payments into **their own** Stripe accounts (and later GoCardless and PayPal).
Card data must never touch our systems (PCI SAQ-A). Payments must post to the E10 ledger
exactly once, even when webhooks are redelivered, arrive out of order, or race the browser
returning from the pay page. Webhooks for every tenant arrive on one platform URL before
any tenant is known. An invoice must never have two collection attempts in flight.

## Decision
1. **Provider interface** (`payments/providers`): accounts, customers, setup intents,
   off-session charges, payment intents, refunds, fees and webhook parsing. `StripeProvider`
   uses Stripe Connect (Standard accounts, direct charges with the `Stripe-Account` header,
   and an optional platform application fee). Without keys, a deterministic
   `FakeProvider` is used, so development and tests run every flow.
2. **Hosted fields only.** The pay and setup pages load Stripe.js from js.stripe.com and
   mount the Payment Element; we store only provider references, brand, last 4 and expiry.
3. **Webhooks** go to `POST /webhooks/stripe`, which is exempt from tenant resolution. The
   signature is verified, and the connected account is mapped to its organisation through
   `AccountRoute`, a small platform table written when an account is connected. The raw
   event is then stored per tenant (`ProviderWebhookEvent`, unique by event id) and
   processed by a retrying Celery task. Unknown accounts get a 200 and are ignored.
4. **Idempotency.** `Payment` is unique by provider reference, so the webhook and the pay
   page's confirm call record a payment once, whichever arrives first. Off-session charges
   carry an idempotency key derived from the attempt (`PaymentAttempt.idempotency_key` =
   the Temporal activity id).
5. **Collection lock.** `PaymentCollectionWorkflow` (`collect:{org}:{invoice}`) is the
   lock: a manual "collect" while it runs returns 409 `collection_in_progress`. Retries,
   direct-debit confirmation waits and failure notices live in the workflow, so there is
   no `next_retry_at` column.
6. **Money flow.** A payment posts `payment` to the ledger and then allocates to invoices
   (oldest first, unless the user chooses), through billing's `allocate_payment`. A payment
   against a payment request becomes credit through `pay_payment_request`. Refunds and lost
   disputes post `refund` entries and un-allocate the invoices, which reopen unless a
   credit note is issued.

## Consequences
- Moving a client between providers is choosing a different default method; full
  migration workflows come with GoCardless (Phase 2).
- `AccountRoute` is the one table read outside a tenant context, like host-to-tenant
  resolution. It holds no customer data.
