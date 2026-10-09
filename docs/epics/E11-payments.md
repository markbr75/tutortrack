# E11 — Payments Processing

| | |
|---|---|
| **Phase** | MVP (Stripe + manual); Phase 2 (GoCardless, PayPal, Open Banking) |
| **Depends on** | E10 |
| **Parity** | TutorCruncher Stripe Standard/Connect, GoCardless DD, bank transfer, split payments, multi-currency; TutorBird Stripe, PayPal, Auto-Pay, cash/cheque |

## 1. Summary
Collect money from clients through a **provider-agnostic payment layer**: card and wallet payments, direct debit mandates, PayPal, bank transfer (with reconciliation), and manual methods. It covers saved payment methods, auto-pay, payment links, allocation to invoices, refunds, disputes and failure handling. Fixes TutorCruncher's reported issue with switching clients between providers.

## 2. Architecture
- `PaymentProvider` interface: `create_customer`, `create_setup_intent`/`create_mandate`, `charge(payment_method, amount, metadata, idempotency_key)`, `create_checkout(invoice|request)`, `refund`, `parse_webhook`, `get_payout_reports`.
- Implementations: `StripeProvider` (Connect), `GoCardlessProvider`, `PayPalProvider`, `ManualProvider`.
- **Connected accounts:** tenants connect **their own** accounts (Stripe Connect **Standard or Express** with the platform as application; GoCardless partner OAuth; PayPal partner referrals). Funds go to the tenant. The platform can take an optional **application fee** (used by the revenue-share plan in E04).
- Per branch: one account per provider (different branches may have different Stripe accounts/currencies).
- Webhooks: `POST /webhooks/{provider}/{account_ref}`, verified signatures, stored raw (`ProviderWebhookEvent`), processed idempotently by a Celery task.

## 3. Functional requirements

### FR-11-1 Provider onboarding
- Settings → Payments: connect Stripe (Connect OAuth/onboarding link), GoCardless, PayPal; show status (charges enabled, payouts enabled, requirements due); disconnect (blocked when there are active mandates/auto-pay without a migration plan).
- Choose enabled methods per branch: card, Apple/Google Pay, BACS/SEPA/ACH/BECS direct debit (via Stripe or GoCardless), PayPal, bank transfer, cash, cheque, other.
- Surcharge settings (where legal): pass card fees on as a % fee line (disabled for UK/EU consumer cards by default).

### FR-11-2 Saved payment methods and mandates
- Clients add cards (Stripe SetupIntent / Payment Element) or set up DD mandates (Stripe or GoCardless hosted flow) from the portal, an onboarding link, or the booking flow; staff can send a "set up payment method" link (never type card numbers themselves).
- `PaymentMethod(client, provider, type, brand, last4, exp, mandate_status, is_default, provider_ref)`; expiring-card notifications.
- **Provider migration:** moving a client from GoCardless to Stripe (or vice versa) explicitly sets which method is default for auto-pay; the old mandate stays usable until cancelled, and the system prevents double collection for the same invoice (an invoice-level **collection lock** while any attempt is pending).
- **AC:** an invoice cannot have two in-flight collection attempts; a second attempt is rejected with `collection_in_progress`.

### FR-11-3 Auto-pay
- Per client toggle (with explicit client consent captured: timestamp, text version, IP). Charges the default method when an invoice is issued (or N days before due, setting), or when a payment request is created.
- DD: GoCardless/Stripe DD payments are created with the appropriate charge date; status `pending` until confirmed (3–5 days).
- Failure handling: retry schedule (card: +3 days, +5 days; DD: one retry), notify client with a pay-now link, notify staff after final failure, optionally pause auto-pay.

### FR-11-4 Pay-now links and checkout
- Every invoice and payment request has a hosted payment page (tenant-branded, on the tenant domain) supporting enabled methods; partial payments allowed (setting); option to save the method for future auto-pay.
- Payment page shows the invoice summary, PDF download and outstanding balance.
- Payment links for arbitrary amounts (e.g. deposits) that create a payment and a credit.

### FR-11-5 Recording manual payments
- Staff record bank transfer, cash, cheque or other: amount, date, method, reference, client, allocation. Bulk entry grid.
- **Bank reconciliation (Phase 2):** import bank statement (CSV/OFX) or bank feed via Open Banking (TrueLayer/Plaid/GoCardless Bank Account Data) and auto-match by invoice number/reference/amount with a confirmation queue.

### FR-11-6 Allocation
- A payment is allocated to one or more invoices (oldest first by default, or chosen); the unallocated remainder becomes client credit. Re-allocation is possible (audited).
- **Split payments:** a payment can be split across multiple clients' invoices (e.g. one school pays for many students) — TutorCruncher parity.

### FR-11-7 Refunds
- Full/partial refund to the original method (provider API) or recorded manual refund; refund of client credit balance; reason; posts ledger entry; linked credit note if refunding an invoice.

### FR-11-8 Disputes / chargebacks
- Webhook-driven `disputed` state; staff alert; evidence submission link; on loss, ledger reversal entry and invoice reopened.

### FR-11-9 Multi-currency
- Payments are in the invoice currency; provider must support it (validated). Stripe Connect accounts with multiple currencies supported. FX is the provider's responsibility; we record the settlement currency/amount from provider balance transactions for reporting (E26).

### FR-11-10 Payout reconciliation
- Import provider payouts (Stripe payouts/balance transactions, GoCardless payouts) with fees, so that E23 accounting sync can post: gross receipts, fees, net to bank.

### FR-11-11 Receipts
- Payment receipt email/PDF (configurable), visible in the portal.

### FR-11-12 Security and compliance
- PCI scope SAQ-A: card data only ever entered in provider-hosted fields/pages. No PAN storage.
- SCA/3DS handled by the provider; off-session charges flagged; "authentication required" failures send the client a link to complete.
- Webhook signature verification; idempotency keys on all provider calls (derived from our payment attempt id).

## 4. Data model
`ProviderAccount(branch, provider, account_ref, status, capabilities, credentials encrypted)`, `ProviderCustomer(client, provider_account, ref)`, `PaymentMethod`, `Mandate`, `Payment(client, amount, currency, method_type, provider, provider_ref, status, received_at, fee_amount, net_amount, source: auto_pay|portal|link|manual|booking, consent_ref)`, `PaymentAttempt(payment, invoice/request, status, failure_code, failure_message, next_retry_at)`, `PaymentAllocation(payment, invoice, amount)`, `Refund`, `Dispute`, `ProviderPayout`, `ProviderWebhookEvent`, `AutoPayConsent`, `BankStatementImport`, `BankTransaction`, `ReconciliationMatch`.

## 5. API
`/api/v1/payments/providers` (connect/disconnect/status), `/payment-methods` (setup sessions), `/payments` (record manual, list), `/payments/{id}/{allocate,refund}`, `/invoices/{id}/collect` (charge default method), `/pay/{token}` (public payment page API), `/bank-reconciliation/*`, `/webhooks/{provider}/{ref}`.

## 6. Events
`payment.succeeded`, `payment.failed`, `payment.pending`, `payment.refunded`, `payment.disputed`, `payment.dispute_closed`, `payment_method.added/updated/expiring/removed`, `mandate.created/active/cancelled/failed`, `provider_account.connected/disconnected/requirements_due`, `payout.received`.

## 7. Permissions
`payments.provider.manage` (Owner/Finance), `payments.payment.{view,record,allocate,refund}`, `payments.autopay.manage`.

## 8. Testing
- Stripe test mode + `stripe-cli` fixtures; GoCardless sandbox; PayPal sandbox.
- Webhook replay and out-of-order event tests; idempotent processing; double-collection prevention.

## 9. Delivery plan
- [x] **E11-T01** Provider interface, ProviderAccount, webhook ingestion pipeline (store raw → process idempotently).
- [x] **E11-T02** Stripe Connect onboarding and account status.
- [x] **E11-T03** Payment methods via SetupIntent; portal and staff-sent setup links; consent capture.
- [x] **E11-T04** Payment, attempt and allocation models; ledger posting via E10 services; manual payment recording.
- [x] **E11-T05** Hosted pay page for invoices/payment requests (Payment Element, wallets).
- [x] **E11-T06** Auto-pay on issue, retry schedule, failure notifications, collection lock.
- [x] **E11-T07** Refunds and disputes.
- [x] **E11-T08** Stripe payouts/balance transactions import.
- [x] **E11-T09** Receipts.
- [x] **E11-T10** Frontend: payments settings, client payment methods, record payment, allocation UI.
- [ ] **E11-T11** (Phase 2) GoCardless provider (mandates, payments, payouts).
- [ ] **E11-T12** (Phase 2) PayPal provider.
- [ ] **E11-T13** (Phase 2) Bank statement import and Open Banking feeds with matching queue.
- [ ] **E11-T14** (Phase 2) Split payments across clients.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E11-TW1** Payment collection, dispute and provider-migration workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `PaymentCollectionWorkflow` `collect:{org}:{invoice}` | Invoice issued with auto-pay, or manual "collect" | Charge default method (activity, idempotency key) → for direct debit wait for `confirmed`/`failed` webhook signal (days) → retry schedule (card +3d, +5d; DD once) → notify client with pay link → final failure notify staff. The workflow *is* the per-invoice collection lock (FR-11-2) | PaymentAttempt `next_retry_at` + retry beat job |
| `DisputeWorkflow` | Provider `dispute.created` webhook | Alert staff → evidence deadline timer with reminders → outcome signal → ledger reversal and invoice reopen if lost | Manual tracking |
| `ProviderMigrationWorkflow` | Admin moves a client between providers | Send new mandate/card setup link → wait for `method_added` → switch default → cancel old mandate after in-flight collections settle | Manual steps |

## Implementation notes (as built 2026-10-09)
- **App:** `payments` with `ProviderAccount` (per branch or organisation default), `ProviderCustomer`, `PaymentMethod`, `SetupLink`, `AutoPayConsent`, `Payment`, `PaymentAllocation`, `PaymentAttempt`, `Refund`, `Dispute`, `ProviderPayout` and `ProviderWebhookEvent`, all with RLS. There is also a platform `AccountRoute` table for webhook routing. See ADR 0008. Without `STRIPE_SECRET_KEY` a deterministic fake provider is used (development and tests).
- **Onboarding (T02):** `POST /payments/providers/stripe/connect` creates a Standard connected account and returns the Stripe onboarding link (it resumes onboarding if already started). Status comes from `account.updated` webhooks or `refresh`: pending → active, or restricted with requirements. Disconnecting is blocked while auto-pay clients use the account. Enabling individual methods per branch and card surcharges are follow-ups (Stripe's dashboard controls which methods the Payment Element offers).
- **Methods and consent (T03):** staff create a setup link (`/pay/setup/<token>`; only the hash is stored; valid 14 days, single use). The client saves a card or debit mandate in Stripe's Payment Element and may tick the auto-pay consent, which records the wording, a version hash, IP address and user agent. Staff can turn auto-pay off; turning it back on needs a consent on record. Choosing the default method is how a client moves between methods or providers (FR-11-2). The portal entry point comes with E15.
- **Payments (T04):** `POST /payments` records bank transfer, cash, cheque, direct debit or other. Card payments only come through Stripe. The money pays the oldest invoices first or the chosen allocations, and the rest is credit. Payments against payment requests become credit (E10). `allocate` replaces allocations (audited). Split payments across clients are Phase 2.
- **Pay page (T05):** `/pay/<token>` (the invoice's or request's `pay_token`, emailed by E10) shows the summary, PDF and amount due, creates a PaymentIntent (optionally saving the method), and confirms. Partial payments follow `payments.allow_partial`. A payment is recorded once whether the confirm call or the `payment_intent.succeeded` webhook arrives first. Fees and net come from the balance transaction. Payment links for arbitrary amounts use payment requests.
- **Auto-pay (T06, TW1):** `invoice.issued` starts `PaymentCollectionWorkflow` for auto-pay clients with an active default method. Retries follow `payments.card_retry_days` ([3, 5]) or `payments.debit_retry_days` ([3]). Debits stay pending until the webhook confirms or fails them; "authentication required" counts as a failed attempt. Each failure publishes `payment.failed` (with `final` on the last); `payments.pause_autopay_after_failure` is optional. `POST /invoices/{id}/collect` returns 409 `collection_in_progress` while a collection runs.
- **Refunds and disputes (T07, TW1):** refunds go back to the card through Stripe (or are recorded for manual payments). Unused credit is refunded first; then invoices are un-allocated and reopen, unless `credit_note` also credits them. Dispute webhooks mark the payment disputed and start `DisputeWorkflow` (evidence reminders 3 days and 1 day before the deadline). A lost dispute reverses the payment (`refund` ledger entry "Chargeback") and reopens the invoice. Evidence submission stays in Stripe.
- **Payouts (T08):** `payout.paid` webhooks become `ProviderPayout` rows (`/payments/payouts`). Fees are stored per payment. Accounting sync is E23.
- **Receipts (T09):** an emailed PDF receipt per payment (`payments.send_receipts`) and `/payments/{id}/receipt`.
- **Frontend (T10):** Settings → Payments (connect, finish setup, status, disconnect); client billing tabs for Payments (record a payment with allocation, list, refund, receipt) and Payment methods (saved methods, default/remove, setup link, auto-pay); Billing → Payments; "Collect now" on invoices; public pay and setup pages loading Stripe.js from js.stripe.com. The CloudFront CSP now allows Stripe's API and 3-D Secure frames.
- **Fixes along the way:** billing workflows that end early now report completion, so their links don't stay "running". Workflow tests anchor absolute deadlines to the shared test server's clock.
- **Deferred (Phase 2):** GoCardless (T11), PayPal (T12), bank statement import and Open Banking (T13), split payments (T14), and the ProviderMigrationWorkflow that comes with GoCardless.
