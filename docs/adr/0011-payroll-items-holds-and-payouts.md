# ADR 0011: Pay items synced from events, pluggable holds, payouts by method

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E12

## Context
Tutor pay follows lessons that can change after the fact (attendance, duration, cancellation
shares), must never alter what was already paid, and is sometimes held (overdue report,
client hasn't paid, compliance). Organisations pay by different means: bank transfer files
in several national formats, Stripe, by hand, or through their own payroll provider.

## Decision
1. **Pay items mirror billing's charges.** `sync_lesson_pay` computes what each
   `LessonTutor` should earn (rate × duration × pay share, from the E06/E09 snapshot) and
   reconciles: open items (ready or held) are replaced; anything in a pay run or paid stays,
   and the difference becomes an *adjustment* item. Charge shares, paid events and approved
   expenses create items the same way. Items are unique per `source_key`, so handlers are
   idempotent.
2. **Holds are a registry** of named rules (`register_hold_rule`). The built-in rules are
   `report_overdue` and `client_unpaid`, behind settings. E18 adds `compliance`. Rules are
   re-evaluated when the inputs change (report events, invoice payments), and again when a
   run is assembled. A manual hold stays until someone releases it.
3. **Pay runs** collect ready items up to the period end into one payout per tutor and
   currency. Negative or below-minimum totals are carried forward with a warning. Above a
   threshold, a run needs two different approvers. `PayRunWorkflow` drives the run:
   approval, statements, payouts, settlement, finish. A per-branch Temporal Schedule opens
   runs at the cut-off.
4. **Payouts by method:**
   - **Stripe** transfers go out immediately, behind a provider interface with a fake for
     development.
   - **Bank file** payouts wait for a generated file and are marked paid.
   - **Manual** and **payroll-provider** payouts are marked paid by staff.
   
   A failed payout returns its items to *ready* for the next run. Bank files (CSV, BACS
   Standard 18, SEPA pain.001, NACHA, ABA) are pure functions pinned by golden-file tests.
   Generated files are stored encrypted, and downloads are audited.
5. **Statements:** self-employed tutors who accepted the self-billing agreement get a
   self-billing invoice numbered per tutor (`SB-<tutor>-0001`), with VAT when they are
   registered. Everyone else gets a remittance advice. Both are PDF (WeasyPrint).

## Consequences
- Stripe payouts to tutors need the organisation's Stripe setup to act as a Connect platform
  for them, which our Standard-account model (ADR 0008) doesn't give by default. They are
  therefore off unless `PAYROLL_STRIPE_PAYOUTS` is set; bank files are the default route.
- Commission-based pay (% of collected revenue) and Wise remain Phase 3.
