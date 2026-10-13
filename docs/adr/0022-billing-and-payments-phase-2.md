# ADR 0022: Billing and payments Phase 2: packages, plans, late fees, splits, redirect providers and bank reconciliation

- **Status:** Accepted
- **Date:** 2026-10-12
- **Epics:** E10 (T12–T15), E11 (T11–T14). Builds on ADR 0007 (ledger and charge sync),
  ADR 0008 (payment providers and webhooks), ADR 0002 (Temporal), ADR 0015 (integration
  framework).

## Context
Phase 1 billing is an append-only ledger fed by charges that track lessons, with invoices as
the only documents that move money onto the ledger. Phase 2 adds prepaid packages, recurring
fixed fees, late fees with collections, split billing, two more payment providers whose flows
are redirects rather than embedded fields, bank reconciliation and split payments. The rules
that must hold: financial records are never edited after issue, money is `Decimal` rounded
half-up per line, timers live in Temporal (no `next_*_at` columns and sweepers), and E23
accounting sync should keep working without new document types.

## Decision
1. **Everything that is sold or charged is a charge on an invoice.** A package sale, a plan
   period and a late fee are new `Charge` kinds (`package`, `plan`, `late_fee`) invoiced
   through the existing draft/issue path (at once by default). So ledger, credit, payments,
   dunning and E23 sync need no new document type. Corrections are credit notes: cancelling
   a package credits unused value on its sale line; waiving an invoiced late fee credits it.
2. **Package units are a separate append-only movement log.** `PackageConsumption` rows
   (`lesson`, `reversal`, `expiry`, `adjustment`) change `units_used`/`units_expired`;
   nothing is edited. Consumption happens inside charge sync: the package covers a fraction
   of the attendee's price and only the remainder is charged, so overage and attendance
   changes reuse Phase 1's charge reconciliation. Package units are kept off the ledger:
   the client paid the invoice; the unit log is the revenue-recognition record.
3. **Temporal owns every timer.** `PackageExpiryWorkflow` (remind → expire; signals
   `depleted`, `extended`), `BillingPlanWorkflow` (charge each period when it starts;
   `changed` re-plans; continue-as-new), the late-fee and collections steps inside
   `InvoiceDunningWorkflow` behind `workflow.patched("late-fees-collections")` (old
   histories replay unchanged), `ProviderMigrationWorkflow` and a daily Temporal Schedule
   for Open Banking feeds. Activities that act on a deadline compare against the deadline
   the workflow waited for, not the wall clock, so they work under time-skipping and when a
   signal is missed.
4. **Proration is pure functions over dates.** `plans.segments` tiles a plan into period
   segments and `amount_for` charges the day share, rounded half-up per segment. Hypothesis
   tests cover tiling, fractions, month clamping, and split periods summing to the fee ± 1p.
5. **Split billing splits charges, not invoices.** `Money.allocate` splits each lesson or
   plan charge into one charge per payer (each with their own tax treatment), so every
   payer gets ordinary invoices, ledgers and dunning.
6. **Redirect providers are a second protocol.** GoCardless and PayPal implement
   `RedirectProvider` (connect by partner flow, hosted setup/payment pages, batched webhooks,
   payouts) next to the Stripe-shaped `PaymentProvider`; both have fake twins used when keys
   are empty. GoCardless mandates become ordinary saved methods, so auto-pay, the collection
   lock and `PaymentCollectionWorkflow` are unchanged (debits are `processing` until a
   webhook confirms them). GoCardless fees come with payouts and are written onto the
   payments then, which is what E23 posts.
7. **Bank reconciliation records payments through the payment services.** Statement lines
   (CSV, OFX, CAMT.053, Open Banking via the E22 framework) are deduplicated by bank id or a
   hash, matched by scored suggestions, and confirmed into ordinary manual payments, split
   payments or links to payouts. Split payments are a `PaymentGroup` of per-client payments.

## Consequences
- No change was needed in the ledger, invoice, allocation or accounting builders; E23 needs
  only new clearing-account keys (`provider:gocardless`, `provider:paypal`, `method:paypal`).
- Package expiry value is not synced to accounting (revenue was recognised at sale); a
  deferred-revenue treatment would need journals (follow-up).
- Termly plans are four-month periods until E20 provides term dates.
- The collections booking block is a selector (`billing.selectors.booking_block`) that
  scheduling and the E08 self-booking engine must call; payment at booking is
  `payments.services.request_booking_payment`.
- GoCardless OAuth needs registered redirect URIs per tenant host (or a platform relay);
  PayPal has no vaulting, so it is pay-now only; Open Banking consent is given in
  GoCardless's portal.
