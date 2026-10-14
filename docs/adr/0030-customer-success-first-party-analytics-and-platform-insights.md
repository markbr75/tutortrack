# ADR 0030: Customer success in a tenant app, first-party consent-gated analytics, and a platform insights schedule

- **Status:** Accepted
- **Date:** 2026-10-14
- **Epic:** E30 Part 2 (T08–T10). Builds on ADR 0002 (Temporal), ADR 0003 (database roles
  and RLS), ADR 0010 (platform console) and ADR 0028 (privacy provider registry).

## Context
Part 2 adds in-app help, product tours, an onboarding checklist, support chat, product
analytics, tenant health scoring, NPS and SaaS metrics. The epic suggests third-party tools
(Intercom, Help Scout, PostHog, Segment). The constraints:
- Families and children use the product. E29 gives us a cookie banner with an analytics
  category, and the UK Age Appropriate Design Code says no profiling of children.
- The BYPASSRLS connection is only for `platform_admin` (`core/tests/test_rls.py`).
- Recurring and long-running work runs on Temporal, with no `next_*_at` columns or sweepers.
  Until now every Temporal Schedule belonged to one organisation (`ScheduleLink`, paused
  on suspension).
- Money uses `Decimal` and `core.money`, rounded half-up.

## Decision

### 1. A tenant-facing `success` app plus cross-tenant parts in `platform_admin`
- The `success` app holds tenant data with RLS: guidance state (tours, "What's new",
  NPS rest), the setup checklist, survey answers, support conversations and messages, and
  product events. It holds no platform credentials, so the RLS allowlist is unchanged.
- Everything that spans organisations is in `platform_admin` and reads through the
  platform connection: the support inbox, the health worklist, NPS aggregates, usage and the
  funnel, and SaaS metrics.
- The console writes through `tenant_context(org)` and the `success` services, so a support
  reply appears in the organisation's own audit log with the staff member as the actor.

### 2. Help content in the repository
Articles and "What's new" entries are markdown files with front matter in
`success/help/`. A small in-process index searches them, and pages are matched with route
prefixes. The frontend renders a safe markdown subset as React elements, never as HTML. This
needs no CMS account, no network calls and no new dependency, and the content is reviewed
with the code. A CMS can replace `success.help` later without changing the API.

### 3. First-party, consent-gated, pseudonymous product analytics
- `POST /analytics/events` accepts a batch only if all four checks pass:
  - the person's `tt_consent` cookie has `analytics: true`;
  - the organisation setting `privacy.product_analytics` is on;
  - the person has a staff role;
  - support is not viewing as the person.
  
  Otherwise it answers `accepted: 0` and stores nothing. The browser also checks consent
  before it queues anything.
- The actor is `salted_hmac(org:user)`. A one-way hash is still personal data under GDPR,
  so the E29 provider can recompute it to export a count or erase a person's events.
- Routes are stored as patterns. The property filter removes risky keys (name, email,
  phone, text, query...) and values that look like emails, phone numbers, UUIDs, tokens or
  free text.
- The provider seam is `PRODUCT_ANALYTICS_SINKS`, a list of classes with
  `emit(events)`. The default stores `ProductEvent` rows for the console. An exporter to
  PostHog or Segment is a later sink that receives the same filtered events.
- Retention: the `product_usage` category keeps events for 395 days by default.

### 4. Support chat as its own small model
`SupportConversation`/`SupportMessage` have status, unread flags for each side and an
assignee. The E13 inbox was not reused: its threads belong to an organisation's families and
contacts, and they run on comms channels (email, SMS, WhatsApp). Support chat is between the
organisation's staff and us. CSAT is a `SurveyResponse` with `topic support:<id>`.

### 5. A platform Temporal Schedule for nightly insights
- `core.workflows.schedules.ensure_platform_schedule()` creates a schedule that belongs
  to no organisation: `schedule:<process>:platform`, with no `ScheduleLink`, so organisation
  suspension never pauses it.
- `manage.py ensure_platform_schedules` creates the schedule. The Temporal worker task runs
  it before it starts polling.
- `PlatformInsightsWorkflow` (deterministic, `default` queue) works in three steps:
  1. a platform activity lists the organisations;
  2. platform activities score batches of 25, entering each organisation's tenant context
     and writing `SubscriptionSnapshot` and `TenantHealthScore` with `update_or_create` on
     (organisation, day), so retries and reruns are idempotent;
  3. an alert activity emails platform staff once per newly at-risk organisation
     (`alerted_at`).
- If one organisation fails, it is logged and skipped. "Recalculate now" starts the same
  workflow.
- These rows are computed facts, not user changes, so they are not audited. Each
  organisation and day gets one row, overwritten in place.

### 6. SaaS metrics from snapshots, per currency
- MRR comes from list prices: base fee, extra tutors and extra branches, annual / 12,
  rounded half-up to the currency's minor unit.
- Month-end snapshots give MRR, ARR, customers, ARPA, movements (new, reactivation,
  expansion, contraction, churn), customer and revenue churn, NRR, trial conversion and cohort
  retention. All are pure `Decimal` functions in `platform_admin.metrics`, tested with
  Hypothesis.
- Currencies are reported separately and never converted.

## Consequences
- Usage data does not leave the system, and staff decide for themselves. Nothing is
  recorded for families or children. We get fewer events than with an opt-out SDK.
- History for SaaS metrics starts with the first nightly run. A closed organisation's
  snapshots are deleted with it after the E02 retention period. Revenue share is not in MRR.
- Health score weights are code constants. Changing them changes tomorrow's scores but never
  rewrites past rows.
- Support replies show as a dot on the Help button. Email and push notification through comms
  is a follow-up.
