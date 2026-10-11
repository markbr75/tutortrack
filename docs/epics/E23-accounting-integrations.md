# E23 — Accounting Integrations

| | |
|---|---|
| **Phase** | Agency (Phase 2) |
| **Depends on** | E10, E11, E12, E22 integration framework |
| **Parity** | TutorCruncher Xero and QuickBooks Online exports with reconciliation |

## 1. Summary
Keep the tenant's books accurate without double entry: sync contacts, invoices, credit notes, payments, refunds, provider fees and tutor bills/payouts to **Xero**, **QuickBooks Online** and (Phase 3) **Sage Business Cloud**/**FreeAgent**, with account mappings, tracking categories (branches), error handling and an audit of sync status per record.

## 2. Functional requirements

### FR-23-1 Connection and mapping
- OAuth connect per org (or per branch when branches use separate ledgers/companies).
- Mapping UI: revenue accounts per service/product category; tax rate mapping (our tax rates ↔ provider tax codes); payment clearing/bank accounts per payment method/provider; provider fees expense account; tutor cost account (cost of sales) and tutor payables; expense categories; rounding account; tracking categories/classes for branch (Xero tracking, QBO Class/Location).
- Validation that mappings are complete before enabling sync.

### FR-23-2 What syncs (one-way: TutorTrack → accounting, our system of record)
| TutorTrack | Xero | QuickBooks Online |
|---|---|---|
| Client (bill payer) | Contact (customer) | Customer |
| Invoice (issued) | ACCREC Invoice | Invoice |
| Credit note | ACCRECCREDIT CreditNote | CreditMemo |
| Payment + allocation | Payment against invoice | ReceivePayment |
| Unallocated credit / prepayment | Prepayment / Overpayment | Unapplied payment / credit |
| Refund | Refund on credit note/overpayment | RefundReceipt |
| Provider payout (gross, fees, net) | Bank transfer + spend money (fees) | Deposit with fee line |
| Tutor (self-employed) | Contact (supplier) | Vendor |
| Pay run statement / self-bill | ACCPAY Bill | Bill |
| Payout | Payment against bill | BillPayment |
| Expenses (approved) | Bill line / Spend money | Bill/Expense |
| Write-off | Credit note to bad debt | CreditMemo to bad debt |

- Options: sync invoices individually or as **daily summary journals** (for high-volume tenants), sync tutor bills or not, sync from a start date (no historical by default; optional backfill).
- Invoice numbers preserved; our PDF can be attached.

### FR-23-3 Sync engine
- Triggered by outbox events (`invoice.issued`, `payment.succeeded`, etc.) → `AccountingSyncJob` per object, ordered dependencies (contact before invoice before payment), idempotent upserts keyed by external ids, retry with backoff, rate limit compliance (Xero 60/min).
- Status per record: `pending | synced | error | skipped`, last attempt, error message (human-readable mapping of provider errors, e.g. "Account code 200 is archived in Xero").
- Sync dashboard: errors list with "retry", "re-map and retry", "skip"; daily digest of errors to finance.
- **Lock-date awareness:** if the accounting period is locked, post to the first open date with a note (setting) or hold.
- **AC:** an invoice issued, part-paid by card (with Stripe fee) and then refunded produces in Xero: one invoice, one payment, one refund, and fee entries on payout, with the Xero invoice balance matching TutorTrack's at each step.

### FR-23-4 Reconciliation helpers
- Payment references include invoice numbers; Stripe/GoCardless payouts posted as single bank deposits matching bank feed lines.
- Read-back (optional): detect payments recorded directly in Xero/QBO against synced invoices and import them as manual payments (Phase 2b).

### FR-23-5 Exports for others
- CSV/IIF exports for Sage 50, MYOB, generic GL journals (date, account, debit, credit, tax, reference) for unsupported packages.

## 3. Data model
`AccountingConnection` (extends IntegrationConnection), `AccountMapping(kind, key, external_account_id)`, `TaxMapping`, `TrackingMapping`, `ExternalRecordLink(object_type, object_id, provider, external_id, synced_hash, status, error)`, `AccountingSyncJob`.

## 4. Events
`accounting.sync_succeeded/failed`, `accounting.connection_error`.

## 5. Delivery plan
- [x] **E23-T01** Accounting provider interface and sync job engine (ordering, idempotency, status tracking).
- [x] **E23-T02** Xero connection, chart of accounts/tax rates fetch, mapping UI.
- [x] **E23-T03** Xero: contacts, invoices, credit notes, payments, refunds.
- [x] **E23-T04** Xero: payouts and fees; tutor bills and bill payments.
- [x] **E23-T05** QuickBooks Online equivalent (T02–T04).
- [x] **E23-T06** Summary-journal mode and backfill.
- [x] **E23-T07** Sync dashboard, error mapping, retry/skip, digests.
- [x] **E23-T08** GL CSV exports.
- [ ] **E23-T09** (Phase 2b) Read-back of externally recorded payments.
- [ ] **E23-T10** (Phase 3) Sage Business Cloud, FreeAgent, Xero Payroll.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [x] **E23-TW1** Accounting sync workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `AccountingSyncWorkflow` `acct-sync:{org}:{object}` | Financial events via the bridge | Ordered dependent upserts (contact → invoice → payment) as activities with provider rate-limit-aware retries; waits for prerequisite syncs via child workflows; surfaces errors to the sync dashboard; signal `retry` after re-mapping | `AccountingSyncJob` queue + retry job |
| `AccountingBackfillWorkflow` | Admin enables sync with a start date | Page through history in batches with checkpoints and pacing; resumable | One-off scripts |

## Implementation notes (as built 2026-10-10)

**Apps (ADR 0018).** The generic parts stay in `integrations` (E22). Everything about ledgers is in the new `accounting` app:
- `AccountingConnection` is the one-to-one companion of an organisation-level `IntegrationConnection`; this is how it "extends" it. It holds:
  - the sync options: mode, start date, bills on/off, attach PDF and lock-date behaviour;
  - the company name, base currency and lock date;
  - the fetched chart of accounts, tax codes and tracking categories;
  - backfill progress and the daily schedule id.

  Tokens stay on the framework connection.
- `AccountMapping(provider, kind, key)`, `TaxMapping(provider, tax_rate)` and `TrackingMapping(provider, branch)` are keyed by a mapping set (`xero`, `quickbooks` or `export`), not by connection. GL exports therefore work without a connection, and mappings survive a reconnect.
- `ExternalRecordLink(connection, object_type, object_id)` is each record's sync status (`pending|synced|error|skipped`). It stores the external id and number, a content hash, a readable error and its code, attempts, the posted date and meta. `SyncLogEntry` is its attempt history.
- There is no `AccountingSyncJob` table: the queue is Temporal (TW1).
- Every table has RLS.

**Framework extensions.** These are generic and live in `integrations`:
- `ProviderSpec.manage_permission`: Finance (`integrations.accounting.manage`) can connect and disconnect Xero or QuickBooks without `integrations.manage`.
- `Provider.clients`/`fake_clients` add client kinds defined by an app (here `accounting`), each with a fake twin. `Provider.health` feeds `services.check`.
- The OAuth callback passes QuickBooks' `realmId` on as `account_id`. `/oauth/complete` accepts it when the token response doesn't name the account.
- `http.request` raises `Rejected` (not retryable) for 400, 409 and 422. It keeps Xero `ValidationErrors` and QuickBooks `Fault` details as the message.

**Providers (T02, T05).**
- Xero and QuickBooks Online are registered at organisation level (OAuth2 with PKCE).
- The real clients are thin: `accounting/providers/xero.py` and `quickbooks.py`.
- Without `XERO_*`/`QUICKBOOKS_*` keys, a fake ledger stands in (`providers/fake.py`). It keeps balances like a real ledger, stores state in the Django cache and honours idempotency keys. It rejects archived accounts, unknown tax codes, locked periods and over-allocation.

**Documents (T03, T04).** Builders read billing, payments and payroll and never write to them. How each record goes to the ledger:

| TutorTrack | Ledger |
|---|---|
| Client | Contact |
| Tutor | Supplier |
| Issued invoice | Invoice; client credit applied allocates overpayments; a voided invoice is voided |
| Credit note | Credit note allocated to the invoice |
| Write-off | Credit note to the bad-debt account |
| Payment | Payment against each synced invoice; the rest becomes an overpayment |
| Refund | Reopens what it took from invoices; the rest is refunded from credit |
| Stripe payout | One net bank transfer from clearing to the bank, plus fees as spend money (QuickBooks: one deposit with a negative fee line) |
| Approved pay run | One bill per self-employed tutor's payout (employees are skipped) |
| Paid payout | Bill payment |

- **Invoices:**
  - The invoice number is kept and line amounts are tax-exclusive.
  - The revenue account is chosen by service or product category, then the account code saved on the service or product, then the default.
  - The tax code comes from the line's tax rate, and the branch from tracking.
- **Payment references** carry the invoice numbers (FR-23-4).
- **Refunds:** Xero has no negative payments, so the Xero client replaces the invoice payments with smaller ones. In QuickBooks the `ReceivePayment` is reduced instead.
- **Payout fees** are the `Payment.fee`s on that account not covered by an earlier payout. The single net transfer matches the bank feed line.
- **Bills:**
  - Lines are grouped by pay item kind; expenses post to the expense category's account.
  - VAT from the self-billing statement uses the "VAT on self-billing" tax code.
  - The bill number is the self-billing number.
- **Credit note from a refund:** when a refund issues a credit note, the note waits for the refund, because the refund reopens the invoice first.

**Engine (T01, T07).**
- **Idempotency:**
  - `services.sync()` builds the document from the record's current state and compares a content hash.
  - It then upserts under a row lock with the idempotency key `tt-<link>-<hash>`.
  - Credit notes, payments, refunds, payouts and bill payments are issued once: once synced, they are final.
- **Ordering:** prerequisites sync first, as child workflows or inline during a backfill:
  - contact → invoice → payment, credit note or refund;
  - supplier → bill → bill payment.

  When a record syncs, anything that was waiting for it gets a "retry" signal.
- **Errors:**
  - `errors.explain` turns errors into finance language, e.g. "Account code 200 is archived in Xero. Choose another account in the mappings, then retry."
  - The codes are: `account_archived`, `tax_code`, `tax_mapping_missing`, `mapping_missing`, `period_locked`, `reconnect`, `duplicate`, `not_found`, `waiting` and `unavailable`.
  - Retryable errors raise, so Temporal retries them.
  - Any other error marks the record `error`, logs it and publishes `accounting.sync_failed`.
- **Rate limits:** we keep our own budget per company (Xero 55 a minute, QuickBooks 400). Hitting it, or getting a provider 429, becomes `ApplicationError(next_retry_delay=…)`.
- **Lock dates:**
  - The lock date is fetched with the chart.
  - By default, a record dated on or before it posts on the first open date with the note "Originally dated …".
  - With the other setting, it is held as a `period_locked` error.
- **What is skipped:**
  - Records before the start date are skipped unless backfilled. The start date defaults to the day sync is switched on.
  - Drafts are never sent.
- **Dashboard:**
  - It shows counts by status, the error list and each record's log.
  - Retry signals the waiting workflow, or starts a new one. "Re-map and retry" is a mapping edit followed by Retry.
  - Skip lasts until someone retries. "Retry all" retries every error.
- **Switching sync on:** it is refused (422) until the mappings are complete, and it needs the `accounting_integrations` plan feature.

**Temporal (TW1).**
- **`AccountingSyncWorkflow`** (`acct-sync:{org}:{type}:{id}:{event}`, `integrations` queue):
  - **Started by** `invoice.issued/voided/paid/partially_paid/written_off`, `credit_note.issued`, `payment.succeeded/refunded`, `client.updated`, `payout.received`, `pay_run.approved`, `self_billing_statement.issued` and `payout.paid`.
  - **Not started for:** update events on records not yet in the ledger, bills when bill sync is off, or sales records in summary mode.
  - **Each run** plans the work, runs prerequisites as child workflows and pushes with backoff.
  - **On an error** it waits up to 30 days for a `retry` or `skip` signal. Child workflows don't wait; their parent does.
- **`AccountingBackfillWorkflow`:**
  - It works through history one kind at a time, in batches with a checkpoint and pacing.
  - It continues as new every 100 batches and stops on `cancel`.
- **`AccountingDailyWorkflow`:** runs on a Temporal Schedule per organisation at 03:30 local time. The schedule is created on enable and deleted on disable.
- Workflow histories are recorded and replayed.

**Summary journals and backfill (T06).**
- In summary mode, the previous day's sales side becomes one balanced manual journal in the base currency: invoices, credit notes, write-offs, voids, payments, refunds and fees.
- The journal is grouped by account, tax code and tracking. It has an explicit sales-tax liability line, plus a rounding line when needed.
- Payouts and bills still sync individually.
- Backfill is the "Also send history from" date on enable, or `POST …/backfill`.

**Daily run (T07, FR-23-4).**
- It compares the balances of invoices synced in the last 30 days with the ledger, and records any difference in the record's log and meta.
- Importing payments recorded directly in the ledger is T09 (Phase 2b).
- It also sends Finance an `accounting_sync_errors` digest (setting `accounting.error_digest`).

**GL exports (T08).**
- Endpoint: `GET /accounting/export?file_format=generic|sage50|myob|iif&start&end&mapping_set=export|xero|quickbooks`.
- Formats:
  - a generic CSV journal: date, account, debit, credit, tax code, tax, currency, reference;
  - a Sage 50 JD/JC import;
  - a MYOB general journal;
  - a QuickBooks Desktop IIF.
- The exports use the same double entry as summary journals, plus payouts and tutor pay. Account codes come from the `export` mapping set, edited on the page.
- Exports are audited as `gl_export` and need `integrations.accounting.export`.

**API.**
- `/accounting/connections`: list, detail and `PATCH` options; `POST` to adopt a new connection; actions `refresh`, `chart`, `enable`, `disable`, `backfill`, `cancel-backfill` and `disconnect`.
- `/accounting/mappings/{provider}`: `GET` and `PUT`.
- `/accounting/records`: filter by `status`, `object_type`, comma-separated `object_id` or `connection`; actions `retry`, `skip` and `retry-failed`.
- `/accounting/export`.
- Permissions are `integrations.accounting.view/manage/export`. Finance already had `integrations.accounting.*`.

**Frontend.**
- Admin **Settings → Accounting** covers:
  - connecting, with the company and lock date shown, refresh and disconnect;
  - the sync options;
  - mappings: accounts, specific accounts, tax codes, branch tracking and remaining problems;
  - switching sync on, with an optional backfill and its progress;
  - the sync dashboard;
  - GL exports.
- Sync badges appear on the invoice page and in payment lists, e.g. "In Xero", or "Xero sync error" with the reason.
- The E22 integrations page now passes on `account_id` as well.

**Deviations.**
- Per-branch ledgers are not built. There is one ledger per organisation, and branches become tracking categories or classes.
- Changes made after a payment has synced are not sent:
  - reallocations of the payment;
  - lost disputes.
- Bad-debt write-offs carry no VAT adjustment.
- Summary journals:
  - post VAT to a mapped liability account;
  - skip currencies other than the base currency.
- Expenses go to the ledger as lines on the tutor's bill, not as separate spend money.
- GL exports leave out self-billing VAT on payroll.
- The real clients are only tested against request shapes, because there are no credentials.
- T09 and T10 are later phases.
