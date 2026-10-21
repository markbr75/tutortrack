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
- [x] **E23-T09** (Phase 2b) Read-back of externally recorded payments.
- [x] **E23-T10** (Phase 3) Sage Business Cloud, FreeAgent, Xero Payroll.

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

## Phase 2b implementation notes (as built 2026-10-14)
- **T09 read-back (FR-23-4).** A connection option `import_payments` (off by default) makes the daily run (`AccountingDailyWorkflow`'s activity, before the reconciliation check; no workflow change) and `POST /accounting/connections/{id}/read-back` ("Check now") ask the ledger for the payments on each synced invoice TutorTrack still shows as owed (up to 200 a run).
- **Provider interface.** `AccountingClient.invoice_payments(creds, invoice_id) -> [LedgerPayment]`: Xero reads the invoice's `Payments` (deleted ones skipped); QuickBooks reads the invoice's linked `Payment`s and the amount each applies to it; the fake ledger has `FakeLedger.record_payment(...)` to simulate a payment entered in the ledger.
- **What is imported.** A ledger payment TutorTrack didn't post (not a synced payment's id, a split part or a refund's replacement payment) becomes an E11 manual payment through `payments.services.record_manual_payment`, allocated to that invoice, dated as in the ledger, with the method of the mapped clearing account (else bank transfer). Its `ExternalRecordLink` is created already synced with the ledger id, so the sync engine never pushes it back.
- **Idempotent with reconciliation logging.** `LedgerPaymentImport` (RLS, unique per connection and ledger payment) records every outcome: `imported` (with the payment) or `skipped` with the reason (more than TutorTrack says is owed, invoice no longer open, no amount). The invoice's sync log gets an `imported` or `skipped` entry, and `accounting.payment_imported` is published. `GET /accounting/payment-imports?status=` lists them on the accounting settings page.
- **Deviation:** summary-journal mode has no per-invoice ledger records, so read-back only runs in individual mode.

## Phase 3 implementation notes (as built 2026-10-14)
See ADR 0032. Kept apart from the Phase 2b read-back (T09) in separate modules.

- **Sage Business Cloud Accounting and FreeAgent:** two more ledgers on the unchanged sync engine (`PROVIDERS` now `xero, quickbooks, sage, freeagent`), registered in the E22 integration framework with OAuth2 (`SAGE_CLIENT_ID/SECRET`, `FREEAGENT_CLIENT_ID/SECRET`, `FREEAGENT_SANDBOX`) and the fake ledger when unconfigured. Mapping sets, dashboards, retries, lock dates, summary journals and backfill work as for Xero.
  - `providers/sage.py` (API v3.1, `X-Business`): contacts (customer/vendor), sales invoices, purchase invoices (tutor bills), sales credit notes allocated through contact allocations, contact payments (receipts, vendor payments, refunds) allocated per invoice, payouts as a bank transfer plus an "other payment" for fees, journals; void by `DELETE` with a reason.
  - `providers/freeagent.py` (API v2, records identified by URL): contacts, invoices marked as sent, bills, credit notes, bank transaction explanations for payments, refunds and payouts (transfer + fees), journal sets; void by the `mark_as_cancelled` transition.
  - Both go through `core.net.safe_urlopen`; they are tested against request shapes (no sandbox credentials in CI) and the shared ledger flow tests (invoice, part payment with fee, refund, payout) run on their fakes.
- **Xero Payroll (FR-12-8):** a separate organisation connection `xero_payroll` (same Xero app, payroll scopes only, so ledger-only customers are never asked for payroll access), connected from Settings → Accounting → Xero Payroll.
  - `PayrollEmployeeLink` (RLS) links employed tutors to Xero employees by email (or by hand); `AccountMapping(provider="xero_payroll", kind="earnings_rate")` holds the earnings rate (default: the first ordinary-earnings rate).
  - On `pay_run.approved` (when connected and the run has employed tutors' hours), `XeroPayrollSyncWorkflow` (`xero-payroll:{org}:{run}:{attempt}`) sends one draft timesheet per employee with a line per day (`payroll.selectors.employee_timesheets`), idempotent per tutor (`Idempotency-Key: tt-<sync>-<tutor>`), retried through rate limits and outages, and records `PayrollTimesheetSync` with each tutor's timesheet or problem (`no_employee`, `no_hours`). Bonuses and reimbursements aren't timesheet units: they are listed in the result for the payroll administrator (and stay in the E12 CSV export). History `XeroPayrollSyncWorkflow-synced.json` is replayed.
  - API under `/accounting/xero-payroll` (status, match, links, employees, earnings-rate, sync, syncs).
- **Sub-processors:** Sage and FreeAgent, and Xero Payroll (UK) added as optional.
- **Merged with T09 (2026-10-14):** payment read-back is limited to Xero and QuickBooks (`readback.READ_BACK_PROVIDERS`); switching it on for Sage or FreeAgent is refused until their clients implement `invoice_payments` (tracked in `docs/05-gap-backlog.md`).

## Gap backlog (as built 2026-10-14)

Batch G3 of `docs/05-gap-backlog.md`; design in [ADR 0037](../adr/0037-gap-batch-g3-scheduling-billing-payments-payroll.md).

- **Package deferred revenue (FR-23-2, FR-26-2; E10:162):** `accounting.package_deferred_revenue` (off by default) posts package sales to a new mapping kind `deferred_revenue` (required while it is on) instead of revenue, and releases the revenue as units are used or expire: Dr deferred revenue / Cr revenue (key `package`, then the sale's keys) per package and local day (`journals.package_postings`, amounts from `billing.packages.recognised_net`, so the releases add up exactly to the sale's net). Summary mode carries the lines in the daily summary journal and GL exports; individual mode syncs a daily `package_revenue` journal from the daily housekeeping. A refunded cancellation's credit note debits the liability; the release on that day trues up the rest.
- **Discount lines (gap G3, E06):** separately shown discount lines post to the revenue account of the lesson line they belong to (`builders.line_charge`).

## Gap backlog (as built 2026-10-21)

Batch G5 of `docs/05-gap-backlog.md` (the accounting items, G5b); design in [ADR 0043](../adr/0043-gap-batch-g5b-accounting.md). This closes the *Deviations* above except where noted.

- **Payment read-back for Sage and FreeAgent (E23-T09):** `readback.READ_BACK_PROVIDERS` is now all four ledgers. Sage: `GET /sales_invoices/{id}` (skips the next call when nothing is applied), then the contact's `/contact_payments` (`CUSTOMER_RECEIPT`s only, deleted ones skipped) and the amount each `allocated_artefacts` entry applies to the invoice. FreeAgent: the invoice's `paid_value`, then bank transaction explanations on every bank account from the invoice date whose `paid_invoice` is the invoice (positive only; bank accounts and explanations fetched once per run, 100 a page, at most 20 pages). Fixed on the way: FreeAgent payment parts are bare explanation URLs, which `our_payment_ids` read character by character, so the second and later parts of a split payment would have been imported.
- **Per-branch ledgers (FR-23-1):** integration connections gain a `branch` level (`IntegrationConnection.branch`, unique per organisation, provider and branch; OAuth start takes `level=branch` and `branch`; the `integration.*` events carry `branch_id`). Only the four ledgers allow it. `AccountingConnection.branch` (null = the organisation's ledger). Records go to their branch's switched-on ledger, else the organisation's (`accounting.routing`); prerequisites sync into the same ledger, so a client can be a contact in two ledgers, and `client.updated` updates every ledger the client is in. One switched-on ledger for the organisation and one per branch (422 otherwise). `SyncInput.connection_id` carries the ledger through the workflow (empty = route the record; old histories replay). Summary journals, backfills, the daily run and GL exports take a branch scope; GL exports also take `branch`, and a branch ledger's own mapping set exports only its records. Mapping sets for branch ledgers are `<provider>@<branch id>` (columns widened to 64). The connection API adds `branch`, `branch_name` and `mapping_set`. Settings → Accounting: a **Ledger** picker when there is more than one, and **Separate ledgers for branches** (branch + connect buttons; shown with two or more branches).
  - *Deviation:* a payment allocated to an invoice of another branch whose ledger differs posts that share as unallocated credit in the payment's ledger (each ledger only sees its own invoices). Records already synced stay in the ledger they went to when a branch ledger is switched on later.
- **Reallocations and lost disputes after sync (FR-23-2/3):** `payments.reallocate` publishes `payment.reallocated` (`before`/`after` per invoice). A `reallocation` record (keyed by the payment, not issued-once) moves the ledger payment from what the ledger holds (`ExternalRecordLink.meta.ledger` on the payment's link, written on its push and after every refund, chargeback and reallocation; worked out from the allocations at sync time for older links) to the allocations now, plus what refunds and chargebacks not yet posted took (they post next). Xero deletes and re-creates the changed invoice payments on the payment's date (freed money becomes an overpayment, credit moved onto invoices is an overpayment allocation); QuickBooks replaces the `ReceivePayment` lines; Sage replaces the receipt's `allocated_artefacts`; FreeAgent deletes and re-creates the payment's explanations. The payment's link records the provider's new part ids. An `accounting.payment_reallocated` subscriber marks the reallocation pending as the event arrives, and a refund or chargeback planned meanwhile waits for it. A lost dispute is a `chargeback` record (the dispute) sent as a refund from the payment; `payments.close_dispute` now saves the dispute last so `closed_at`..`updated_at` brackets the allocations the loss took back. Summary journals and GL exports post chargebacks (Dr receivable / Cr clearing). The payment document now nets a reallocation made before the payment synced.
  - *Deviation:* Stripe's dispute fee isn't posted (TutorTrack doesn't record it). A Xero reallocation can't undo an earlier overpayment allocation (it only changes cash payments).
- **Summary journals in other currencies (FR-23-2):** the daily run posts one more journal per currency with activity that day (`<day>:<currency>`; backfills too), converted posting by posting into the base currency at the day's platform rate (E26 `FxRate`, latest on or before the day), rounded half-up, and balanced on the new optional mapping kind `fx` ("Currency conversion differences", else rounding). The narration names the rate. No rate → `fx_rate_missing` error until retried.
- **Bad-debt VAT adjustment (FR-23-2):** org setting `accounting.bad_debt_vat_relief` (off). The amount written off is split over the invoice's tax rates by gross (largest remainder) and each part's VAT is that rate's VAT fraction, rounded half-up; the write-off credit note has a line per rate with that VAT and tax code, and journals/exports debit sales tax with it. Hypothesis checks the split.
- **Self-billing VAT in GL exports (FR-23-5):** a bill with a VAT-registered tutor's self-billing VAT debits the new optional mapping kind `input_tax` (else the sales tax account) with the self-billing tax code, and credits payables with net + VAT, as the synced bill does.
  - *Deviation (unchanged behaviour, noted):* the payout pays the net, so the VAT stays in payables until settled outside TutorTrack, in exports and in synced bills alike.
- **Not built:** live testing against the providers (no credentials); the real clients are tested against request shapes and every flow runs on the fake ledgers.
