# ADR 0037: Gap batch G3 — scheduling, delivery, billing, payments and payroll

- **Status:** Accepted
- **Date:** 2026-10-14
- **Scope:** `docs/05-gap-backlog.md` batch G3 (E06–E12, with E23, E24 and E26). Builds on
  ADR 0006 (delivery), ADR 0007 (ledger and charges), ADR 0008 (payments), ADR 0011
  (payroll), ADR 0021/0022 (Phase 2 pricing, booking, packages) and the E32 workflow rules.

## Context
Every ticket of E06–E12 is ticked, but their notes deferred seventeen pieces of spec: discounts
could only be netted, "jobs needing attention" ignored lessons, balances and reports, the
calendar lacked saved filters, a second time zone, printing and bulk actions, the booking
cancellation window was stored but not enforced, the website builder had no booking block,
the termly free-cancellation limit, real report attachments and the override screens were
missing, tutors could not check drafts, credit notes had no PDF, statements were not sent,
package money was recognised at sale, branches could not choose payment methods or pass on
card fees, cards expired silently, auto-pay only ran on issue, payments had to be recorded
one at a time, full bank details needed no re-authentication, pay-run items could not be
edited and tutors had no annual summary. The constraints: financial records are immutable,
money is `Decimal` rounded half-up per line, financial POSTs take `Idempotency-Key`,
long-running or timed steps are Temporal workflows (no `next_*_at` plus sweeper), and no new
dependencies.

## Decision

### 1. Discounts shown separately are derived lines, never new money
`pricing.discount_display = separate` changes only how a charge is *shown*: the invoice gets
the undiscounted line plus one negative line per discount, linked by `InvoiceLine.parent`
(`kind = discount`). The undiscounted part is the snapshot's undiscounted amount scaled by
what the charge covers (charge % , split share, the part a package didn't pay), rounded
half-up; the discount lines take the exact difference (net, tax and gross), shared by size
with largest remainder. So the lines always sum to the charge, the invoice total and ledger
don't change, and a credit note credits a line *with* its discounts (never more than was
invoiced). Accounting posts discount lines to their parent's revenue account. Property tests
check the sums.

### 2. Tutor pre-review is a gate inside the existing invoice-run workflow
Tutors' checks are records (`TutorInvoiceReview`), not a new workflow. `InvoiceRunWorkflow`
gains a `tutors_done` signal and, behind `workflow.patched("tutor-review")` and only when the
run's stats say tutor review is on, keeps the review window open for
`billing.tutor_review_days` (ending early when every tutor has answered or staff approve).
Old histories replay unchanged (the branch depends on activity results that old runs don't
have). A flag *holds* the drafts with that tutor's lessons (left as drafts for staff); silence
holds nothing, so tutors can never block invoicing by not answering. Tutors never see
amounts (FR-07-1).

### 3. Statements on a Temporal Schedule; card notices on a stateless beat task
Monthly statements are a per-organisation Temporal Schedule (`StatementRunWorkflow`), kept in
sync with the settings like the invoice schedules, sending in batches with comms dedupe keys
per client, currency and period. Expiring-card notices are a short, stateless monthly fan-out
Celery task whose idempotency is the comms and outbox dedupe keys (card + expiry): there is
no state to wait on and no marker column.

### 4. Auto-pay "N days before due" waits inside `PaymentCollectionWorkflow`
The collection workflow is already the invoice's collection lock, so the wait lives there
(`CollectInput.collect_on`, behind `workflow.patched("autopay-before-due")`): one workflow per
invoice from issue to settlement. "Collect now" during the wait signals `collect_now` (found
with a workflow query, because the `WorkflowLink` step can race the link's creation) instead
of being refused.

### 5. Card surcharges are a separate invoice, limited by law
A surcharge is never added to the invoice being paid (issued invoices are immutable). The
pay page charges amount + surcharge (half-up) and, on success, issues the surcharge as its
own invoice (charge kind `surcharge`, no tax, idempotent per provider payment) and allocates
the payment to both. Only online card payments of invoices are surcharged (not prepaid
top-ups, not auto-pay, which the client agreed at the invoice amount). Legal assumptions
(tenants remain responsible for their own compliance):
- **UK** (Consumer Rights (Payment Surcharges) Regulations 2012, amended 2018) and **EEA**
  (PSD2 art. 62(4)) ban surcharges on consumer cards; we cannot tell business cards apart, so
  surcharges are refused for organisations there.
- **United States:** allowed up to the card networks' 3% cap; some states (e.g. Connecticut,
  Massachusetts) ban them — we don't know the organisation's state, so the setting's help says
  to check.
- **Canada:** allowed since October 2022 up to 2.4%, not in Quebec (same caveat).
- **Australia:** allowed up to the cost of acceptance (RBA); we cap at 3%.
- **New Zealand and elsewhere:** capped at 3%.
The cap is checked when the setting is saved and again at payment time (a country change
wins). Methods per branch (`payments.enabled_methods`) limit the pay page's providers and the
manual methods staff can record.

### 6. Package revenue is deferred by a cumulative formula
With `accounting.package_deferred_revenue`, a package sale posts to a `deferred_revenue`
mapping instead of revenue; revenue is released per package and day as
`recognised(t) = round_half_up(sale net × units used or expired before t / units total)`.
Because each day's release is a difference of cumulative values, the releases add up exactly
to the sale's net — no rounding drift. A refunded cancellation recognises the net less the
refund (the credit note debits the liability), so the liability ends at zero. The same
formula drives the E26 "package liabilities" report. Summary mode carries the lines in the
daily journal; individual mode syncs a daily `package_revenue` journal.

### 7. A shared step-up re-authentication
`identity/reauth.py` is the reusable pattern: confirm with password, authenticator/recovery
code or passkey; the time is kept in the server-side session for five minutes; protected reads
raise `reauthentication-required` with the available methods. Failures count towards the
login lockout. Full bank details use it first; other sensitive reads can adopt it.

### 8. Smaller items
- Pay-run item edits are linked `adjustment` items (`PayItem.adjusts`), never edits of the item.
- Annual earnings count items whose payout was paid in the period (calendar year, or the UK
  tax year 6 April – 5 April by default for UK organisations), earnings apart from repaid
  expenses.
- Report attachments are `core.storage` uploads attached to the report, readable by whoever
  can read the report and by families once shared, for client- or student-visible fields.
- The booking cancellation window applies only to lessons families booked online, in the
  portal; staff and the cancellation policy are unchanged.
- "Max free cancellations per term" uses the E20 term containing the lesson's date; lessons in
  the holidays aren't limited by it.
- Saved calendar filters reuse the E05 saved views (`entity_type = "calendar"`).

## Consequences
- Billing gains `TutorInvoiceReview`, invoice line kinds and the `surcharge` charge kind
  (migration `billing.0004`), payroll gains `PayItem.adjusts` (`payroll.0003`); both additive.
- New workflow history files: `InvoiceRunWorkflow-tutor-review.json`,
  `StatementRunWorkflow-sent.json`, `PaymentCollectionWorkflow-before-due.json`.
- New comms types `client_statement`, `tutor_invoice_review`, `staff_invoice_review_flagged`
  and `card_expiring` (the G4 item "missing notification types: card expiring, statement" is
  therefore partly done).
- New events `invoice_run.tutor_review_requested`, `invoice_run.tutor_reviewed`,
  `client.statement_sent`, `payment_method.expiring`.
- Follow-ups: per-state surcharge rules, the US taxpayer-id view behind re-authentication,
  and Stripe-only debits being treated as "card" for method switching.
