# ADR 0043: Gap batch G5b — accounting

- **Status:** Accepted
- **Date:** 2026-10-21
- **Scope:** the accounting items of `docs/05-gap-backlog.md` batch G5 (E23). Builds on
  ADR 0018 (accounting app and sync engine), ADR 0032 (Sage, FreeAgent, Xero Payroll) and the
  E32 workflow rules.

## Context
E23 shipped with one ledger per organisation and several deferrals: payment read-back only
for Xero and QuickBooks; nothing sent when a payment already in the ledger was reallocated or
lost a dispute; write-offs with no VAT adjustment; summary journals that skipped currencies
other than the ledger's base currency; and GL exports without the VAT on tutors'
self-billing invoices. The constraints: synced financial records are final (changes are new
records), money is `Decimal` rounded half-up per line, the sync engine stays a hash-compared
reconciliation driven by `AccountingSyncWorkflow`, no new dependencies, and no real provider
credentials to test against.

## Decision

### 1. Per-branch ledgers are branch-level connections plus routing
- The integration framework gains a `branch` level: `IntegrationConnection.branch` (with its
  own unique constraint per organisation, provider and branch), carried through the OAuth
  state. Only the four ledgers allow it; `org_connection()` ignores branch connections, so no
  other integration changes.
- `AccountingConnection.branch` (null = the organisation's ledger). At most one switched-on
  ledger for the organisation and one per branch (checked on enable).
- `accounting.routing` decides where a record goes: its branch's switched-on ledger, else the
  organisation's. The same rule from a ledger's side is a `Scope` (one branch, or every branch
  except those with their own), used by summary journals, backfills and GL exports.
- The sync workflow carries the ledger: `SyncInput.connection_id` (default empty = route the
  record), set from `plan_sync`'s result and passed to prerequisites (so a client billed by a
  branch ledger becomes a contact *in that ledger*) and to retries. Old histories replay
  unchanged (the field defaults; only activity and child inputs differ). A client update with
  no ledger named goes to every ledger the client is in.
- Mapping sets are keyed `<provider>@<branch id>` for branch ledgers (their charts differ);
  the mapping tables' `provider` column widens to 64 characters. Mappings still survive a
  reconnect.

### 2. Changes after sync are records of their own
- **Lost disputes** become a `chargeback` record (the dispute's id) built as a refund
  document from the payment, so every provider's existing refund push applies. The money it
  took off invoices is the negative allocations written while closing the dispute;
  `payments.close_dispute` now saves the dispute last so `closed_at`..`updated_at` brackets
  them (as a refund's `created_at`..`updated_at` already did).
- **Reallocations** publish a new `payment.reallocated` event. A `reallocation` record (the
  payment's id, not issued-once) is a state reconciliation: the document says what the ledger
  holds of the payment now (`previous`, kept on the payment's link as `meta.ledger` and
  updated after every refund, chargeback and reallocation push; worked out from the
  allocations at sync time for older links) and what it should hold (`allocations`: the
  payment's allocations now, plus what not-yet-posted refunds and chargebacks took, since they
  post next). Providers apply the difference: QuickBooks and Sage replace the payment's
  lines/allocations; Xero deletes and re-creates the invoice payments that change (on the
  payment's date), receiving freed money as an overpayment and allocating the overpayment for
  credit moved onto invoices; FreeAgent re-explains the payment. Provider part ids returned
  by the push are written back to the payment's link so later refunds use live ids.
- Ordering: a subscriber marks the reallocation pending as the event is dispatched; a refund
  or chargeback planned while it is pending waits for it as a prerequisite. A reallocation
  never waits for refunds (it counts them instead), so there is no cycle.
- The payment document itself now nets reallocations made before it synced (it still
  excludes refunds and chargebacks, which post after it).

### 3. Tax and currency
- **Bad debt VAT relief** is an org setting (`accounting.bad_debt_vat_relief`, off). The
  amount written off is split across the invoice's tax rates by gross (largest remainder) and
  each part's VAT is the rate's VAT fraction of it, rounded half-up; the write-off credit note
  then carries a line per rate with that tax, and journals/exports debit the VAT account.
- **Summary journals in other currencies**: one more journal per day and currency
  (`<day>:<currency>`), converted to the base currency with the platform's daily rates
  (E26 `FxRate`), posting by posting, rounded half-up, balanced on an optional
  `fx` mapping ("Currency conversion differences", else rounding). No rate is a readable
  `fx_rate_missing` error that waits for retry. Ledgers' manual journals are base-currency
  only, hence conversion rather than foreign-currency journals.
- **Self-billing VAT in GL exports** mirrors the synced bill: Dr input VAT (optional
  `input_tax` mapping, else the sales tax account, tagged with the self-billing tax code) and
  Cr payables for net + VAT.

### 4. Read-back for Sage and FreeAgent
Sage lists the invoice contact's customer receipts and sums what each allocates to the
invoice; FreeAgent scans bank transaction explanations whose `paid_invoice` is the invoice
(bank accounts and explanations cached per run). FreeAgent payment parts are bare URLs, which
`our_payment_ids` now recognises.

## Consequences
- A branch can move to its own books without touching other branches; records already synced
  stay where they went. Payments allocated across branches with different ledgers post the
  other branch's share as unallocated credit in the payment's ledger.
- Reallocations and chargebacks keep ledger balances in step with TutorTrack, verified on the
  fake ledgers for all four providers; the real clients are tested against request shapes
  only. Xero cannot undo an earlier overpayment allocation through a reallocation.
- Dispute fees are still not posted (TutorTrack doesn't record them).
- New event `payment.reallocated` is in the webhook catalogue (payment aggregate).
