# ADR 0018: Accounting sync by reconciliation on the integration framework

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E23 (builds on ADR 0015, E22)

## Context
Tenants want their invoices, payments, refunds, payouts and tutor bills in Xero or
QuickBooks Online without double entry. There are several constraints:
- TutorTrack is the system of record, and its financial records are immutable.
- Ledgers enforce their own rules: lock dates, archived accounts, rate limits, and no
  negative payments in Xero.
- Events can arrive twice, out of order, or before their prerequisites.
- Finance staff need to see and fix failures themselves.
- There are no provider credentials in development or CI.

## Decision
1. **A separate `accounting` app on top of `integrations`.**
   - Xero and QuickBooks are registered as framework providers. OAuth, encrypted tokens, refresh, health and disconnect are reused unchanged.
   - Only genuinely generic pieces went into the framework:
     - `ProviderSpec.manage_permission`, so finance can connect without `integrations.manage`;
     - app-defined client kinds with fake twins (`Provider.clients`/`fake_clients`) and a provider `health` hook;
     - QuickBooks' `realmId` passed on from the OAuth callback as `account_id`;
     - a non-retryable `Rejected` error for 400/409/422 that keeps the provider's validation message.
   - Ledger concepts (mappings, documents, sync status) stay in `accounting`.
2. **`AccountingConnection` is a 1:1 companion of the framework connection**, not a subclass. It holds the sync options, the fetched chart and the lock date. Mappings are keyed by a *mapping set* (provider key, or `export`), so GL exports need no connection and a reconnect keeps the mappings.
3. **Provider-agnostic documents.**
   - Builders read billing, payments and payroll (never write them) and produce documents: contact, invoice/bill, credit note/write-off, payment/bill payment, refund, payout, journal.
   - Thin clients translate the documents: Xero, QuickBooks, and a fake ledger that keeps balances and enforces the same rules.
   - Provider quirks live in the client. For example, a Xero refund replaces the invoice payments with smaller ones; a QuickBooks refund reduces the `ReceivePayment`; QuickBooks sales lines go through one service item per income account.
4. **Reconciliation, as for calendars.**
   - `sync(type, id)` builds the record's document from its current state and hashes it. It pushes only on change, under a row lock on the record's `ExternalRecordLink`, with an idempotency key derived from link and hash.
   - Records issued once (payments, credit notes, refunds, payouts, bill payments) are final once synced.
   - Duplicate, retried or reordered events are therefore harmless. Event pushes, retries, backfills and the dashboard's Retry all use the same code.
5. **Temporal replaces the job queue.**
   - `AccountingSyncWorkflow` runs once per triggering event. It runs prerequisites as child workflows (contact → invoice → payment), then pushes:
     - transient failures retry with backoff;
     - a 429, or our own per-company budget, sets the next retry delay;
     - anything a person must fix waits for `retry` or `skip` signals from the dashboard.
   - `AccountingBackfillWorkflow` pages through history with checkpoints, pacing and continue-as-new.
   - A per-organisation Temporal Schedule runs `AccountingDailyWorkflow`: summary journal, reconciliation check and error digest.
6. **Errors are explained, not forwarded.** `errors.explain` maps provider and engine failures to a code and a sentence finance staff can act on, such as "Account code 200 is archived in Xero. Choose another account in the mappings, then retry."

## Consequences
- **Testing:** the E23 acceptance criterion runs end to end against the fake ledger for both providers (invoice → card payment with fee → refund → payout, balances equal at each step). The real clients are covered only by request-shape tests until sandbox credentials exist.
- **Production setup:** the Xero and Intuit apps need the redirect URI `$APP_URL/api/v1/integrations/oauth/callback` and the keys `XERO_CLIENT_ID/SECRET` and `QUICKBOOKS_CLIENT_ID/SECRET`.
- **One ledger per organisation:** branches map to tracking categories or classes. Per-branch companies would need several organisation-level connections per provider, which the framework's uniqueness rule doesn't allow yet.
- **Read-back is detection only:** payments recorded directly in the ledger are flagged by the daily balance check but not imported. Importing them is T09, Phase 2b.
