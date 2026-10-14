# ADR 0031: Phase 2b on existing seams: signed public links, feedback on Temporal, a privacy-safe people map, ledger payment read-back and a whitelisted report builder

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epics:** E05-T12 (map view), E09-T09 (feedback micro-surveys), E17-T09 (proposals), E19-T08 (client shortlist sharing), E23-T09 (read-back of externally recorded payments), E26-T08 (custom report builder). Builds on E13 comms, E24 public profiles, E25 reviews, E29 consent and privacy, E31 (which calls `reports.run`).

## Context
Six deferred tickets in finished epics share three needs: families act on a link without
an account (rate a lesson, accept a proposal, choose a tutor); staff need new views over
data that is already there (where people are, what families think, ad hoc reports); and
data has to flow back from an external ledger without ever double counting. Each ticket
had to extend its own app, not add new ones, and keep existing APIs (notably
`reporting.reports.run`, used by the E31 copilot) unchanged.

## Decision
1. **Public links are signed tokens plus database state.** Feedback, proposals and shared
   shortlists use `django.core.signing` tokens salted with the purpose and the
   organisation id (the pattern E25 reviews already use). The token only names the row;
   the row's status and `expires_at` decide what the link may still do, so revoking,
   answering or expiry takes effect at once, a token from another tenant is a 404, and
   nothing has to be stored about the token itself. Public endpoints are unauthenticated,
   throttled with the `public_form` scope and return only what the family needs.
2. **Timers go to Temporal; derived expiry needs nothing.** Feedback requests
   (`LessonFeedbackWorkflow`: delay, send, wait for answers, expire) and proposals
   (`ProposalWorkflow`: reminder, expiry) have real timed steps, so they are workflows
   started by the outbox bridge, with replay histories. A shared shortlist only stops
   working at `expires_at`, which is read at request time: no workflow and no sweeper.
3. **Consent and channels come from the existing layers.** Feedback goes to one contact
   who receives lesson updates; an E29 consent record of type `lesson-feedback` that is
   withdrawn stops it; the E13 type is non-transactional in the `reports` category, so
   preferences and unsubscribes apply. Proposals are transactional (the family asked).
4. **Public tutor cards are one function.** `matching.sharing.tutor_card` decides what a
   family may see about a tutor (first name and initial, approved profile text, approved
   subjects, qualifications, the families' rating; never contact details, addresses, pay
   or scores). Shortlists and proposals both use it. The "families' rating" blends E25
   approved reviews and E09 feedback weighted by count; matching uses the same blend.
5. **Choices feed existing flows through services.** A chosen tutor (shortlist or
   proposal) starts an E19 offer batch via `matching.services`; accepting a proposal
   converts the enquiry via `leads.services.convert` and asks for a deposit via the E10
   payment request and E11 pay page. Nothing writes another app's tables.
6. **Maps without a map library.** The frontend has no map dependency, so the people map
   is an accessible SVG plot plus a table; the API returns coordinates rounded to about
   100 m and an area, never a street. Geocoding stays behind `core.geo` with a
   network-free `FakeGeocoder` for development and tests, and Google/Mapbox through
   `core.net.safe_urlopen` with keys from the environment.
7. **Ledger read-back is idempotent by the ledger's id.** `invoice_payments` joins the
   accounting provider interface. A ledger payment that TutorTrack did not post becomes an
   E11 manual payment, and its `ExternalRecordLink` is created already synced with the
   ledger's id, so the sync engine treats it as issued and never pushes it back.
   `LedgerPaymentImport` (unique per connection and ledger payment) records imported and
   skipped payments with reasons, and the invoice's sync log explains each one. It runs
   inside the existing daily activity, so the daily workflow's code is unchanged.
8. **The report builder is a semantic layer, not a query language.** Datasets declare
   their dimensions (our ORM lookups) and measures (our aggregates); definitions only name
   them. Scoping reuses the standard report families (`reporting.<family>.view` with its
   data scope) plus `reporting.builder.use`. Money is aggregated per currency and rounded
   half-up; totals are separate aggregates (correct for averages). Queries carry a
   statement timeout and a row cap. The standard report engine and `reports.run` are
   untouched; exports reuse the T07 writers.

## Consequences
- Families never need an account for these flows, and a leaked link exposes only a
  minimal, time-limited page for one record.
- New personal data (feedback comments, proposal signatures, shortlist notes) is covered
  by the E29 DSAR export and erasure providers.
- The map can later show tiles (Mapbox/Google) behind the same API; the builder can later
  send heavy queries to a read replica asynchronously and support scheduling.
- Read-back skips anything that doesn't fit (over-payments, closed invoices) for finance
  to resolve; summary-journal mode cannot read back because invoices aren't posted
  individually.
