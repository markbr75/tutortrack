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
- [ ] **E23-T01** Accounting provider interface and sync job engine (ordering, idempotency, status tracking).
- [ ] **E23-T02** Xero connection, chart of accounts/tax rates fetch, mapping UI.
- [ ] **E23-T03** Xero: contacts, invoices, credit notes, payments, refunds.
- [ ] **E23-T04** Xero: payouts and fees; tutor bills and bill payments.
- [ ] **E23-T05** QuickBooks Online equivalent (T02–T04).
- [ ] **E23-T06** Summary-journal mode and backfill.
- [ ] **E23-T07** Sync dashboard, error mapping, retry/skip, digests.
- [ ] **E23-T08** GL CSV exports.
- [ ] **E23-T09** (Phase 2b) Read-back of externally recorded payments.
- [ ] **E23-T10** (Phase 3) Sage Business Cloud, FreeAgent, Xero Payroll.

## Temporal workflows (E32)

Implement these processes as Temporal workflows following the rules in [E32](E32-workflow-orchestration-temporal.md) (deterministic workflow code, side effects in tenant-scoped activities that call services, tenant-prefixed workflow IDs, signals for human decisions). Where the requirements above mention sweeper tasks, `next_*_at` / `resume_at` columns or retry schedules, the workflow replaces them.

- [ ] **E23-TW1** Accounting sync workflows (requires E32).

| Workflow | Started by | Steps, timers and signals | Replaces |
|---|---|---|---|
| `AccountingSyncWorkflow` `acct-sync:{org}:{object}` | Financial events via the bridge | Ordered dependent upserts (contact → invoice → payment) as activities with provider rate-limit-aware retries; waits for prerequisite syncs via child workflows; surfaces errors to the sync dashboard; signal `retry` after re-mapping | `AccountingSyncJob` queue + retry job |
| `AccountingBackfillWorkflow` | Admin enables sync with a start date | Page through history in batches with checkpoints and pacing; resumable | One-off scripts |
