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
- [ ] **E11-T01** Provider interface, ProviderAccount, webhook ingestion pipeline (store raw → process idempotently).
- [ ] **E11-T02** Stripe Connect onboarding and account status.
- [ ] **E11-T03** Payment methods via SetupIntent; portal and staff-sent setup links; consent capture.
- [ ] **E11-T04** Payment, attempt and allocation models; ledger posting via E10 services; manual payment recording.
- [ ] **E11-T05** Hosted pay page for invoices/payment requests (Payment Element, wallets).
- [ ] **E11-T06** Auto-pay on issue, retry schedule, failure notifications, collection lock.
- [ ] **E11-T07** Refunds and disputes.
- [ ] **E11-T08** Stripe payouts/balance transactions import.
- [ ] **E11-T09** Receipts.
- [ ] **E11-T10** Frontend: payments settings, client payment methods, record payment, allocation UI.
- [ ] **E11-T11** (Phase 2) GoCardless provider (mandates, payments, payouts).
- [ ] **E11-T12** (Phase 2) PayPal provider.
- [ ] **E11-T13** (Phase 2) Bank statement import and Open Banking feeds with matching queue.
- [ ] **E11-T14** (Phase 2) Split payments across clients.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E11-TW1** Payment collection, dispute and provider-migration workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `PaymentCollectionWorkflow` `collect:{org}:{invoice}` | Invoice issued with auto-pay, or manual "collect" | Charge default method (activity, idempotency key) → for direct debit wait for `confirmed`/`failed` webhook signal (days) → retry schedule (card +3d, +5d; DD once) → notify client with pay link → final failure notify staff. The workflow *is* the per-invoice collection lock (FR-11-2) | PaymentAttempt `next_retry_at` + retry beat job |
| `DisputeWorkflow` | Provider `dispute.created` webhook | Alert staff → evidence deadline timer with reminders → outcome signal → ledger reversal and invoice reopen if lost | Manual tracking |
| `ProviderMigrationWorkflow` | Admin moves a client between providers | Send new mandate/card setup link → wait for `method_added` → switch default → cancel old mandate after in-flight collections settle | Manual steps |
