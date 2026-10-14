# E30 — Platform Administration, Support & Operations

| | |
|---|---|
| **Phase** | MVP (part 1) → Scale (part 2) |
| **Depends on** | E01–E04 |

## 1. Summary
Internal tooling for the TutorTrack team: a super-admin console for tenants, plans, feature flags and support; safe impersonation; operational monitoring, alerting, backups and runbooks; in-app help and onboarding guidance; product analytics and tenant health scoring.

## 2. Functional requirements

### Part 1 (MVP)

#### FR-30-1 Super-admin console
- Separate app area (`/platform`) restricted to `is_platform_staff` users with mandatory 2FA and IP allowlist; uses the RLS-bypass DB alias only here.
- Tenants list: search, filters (plan, status, region, created, MRR, last activity), tenant detail (org info, subscription, usage, users, integrations, recent errors, audit), actions: extend trial, grant entitlement override (E04), suspend/unsuspend, change plan (with note), resend owner verification, trigger data export, schedule deletion.
- Plans and prices management (E04); feature flag management with targeting (global %, plan, org list).
- Outbox/dead-letter viewer and replay; Celery queue depth; webhook/integration failure overview.

#### FR-30-2 Support impersonation
- "Log in as" a tenant user only with a **reason/ticket reference** and optional tenant-granted access (org setting: "allow support access" with time-limited grants); read-only by default; full audit visible to the tenant Owner ("Support accessed your account on…").

#### FR-30-3 Observability and operations
- Sentry, OTel tracing, metrics dashboards (Grafana/CloudWatch): request latency/error rates, Celery task latency/failures, outbox lag, email/SMS delivery rates, payment webhook lag, DB health.
- Alerting (PagerDuty/Opsgenie) with SLO-based alerts: API availability, outbox lag > 60s, invoice run failures, payment webhook backlog.
- Runbooks in `docs/runbooks/` (deploy, rollback, DB restore, provider outage, incident comms).
- Status page (e.g. Instatus/Statuspage) with component statuses; in-app outage banner (TutorCruncher parity).

#### FR-30-4 Backups and DR
- PITR + daily logical backups to a separate account; quarterly restore drill; RPO ≤ 5 min, RTO ≤ 4h; per-tenant restore tool (restore one org's data into a staging DB for recovery of accidental deletions).

### Part 2 (Scale)

#### FR-30-5 In-app help and onboarding
- Contextual help panel with articles (headless CMS/help centre integration, e.g. Intercom/Help Scout), product tours for key flows, onboarding checklist on the dashboard (set up service, add student, schedule lesson, connect Stripe, send first invoice) with progress tracking, in-app chat support widget (Intercom), changelog/what's new.

#### FR-30-6 Product analytics and tenant health
- Event tracking (PostHog self-hosted or Segment) of feature usage (no PII in properties); funnels for onboarding.
- Tenant health score (usage depth, active tutors trend, payments volume, errors, support tickets, NPS) for customer success; churn risk alerts.
- NPS/CSAT in-app surveys.

#### FR-30-7 Platform billing operations
- MRR/ARR, churn, expansion dashboards from E04 data; dunning oversight; revenue share reconciliation.

## 3. Delivery plan
- [x] **E30-T01** Platform staff auth hardening, `/platform` area, tenant list/detail.
- [x] **E30-T02** Tenant actions (trial extend, overrides, suspend, plan change) with audit.
- [x] **E30-T03** Feature flag management UI with targeting.
- [x] **E30-T04** Outbox/dead-letter/queue monitoring views and replay.
- [x] **E30-T05** Support impersonation with tenant-granted access and tenant-visible audit.
- [x] **E30-T06** Observability dashboards, SLO alerts, status page and outage banner.
- [x] **E30-T07** Backup/restore drills and per-tenant restore tool; runbooks.
- [x] **E30-T08** (Scale) Help panel, product tours, onboarding checklist, support chat.
- [x] **E30-T09** (Scale) Product analytics, tenant health scoring, NPS.
- [x] **E30-T10** (Scale) SaaS metrics dashboards.

## Implementation notes (part 1, as built 2026-10-10)
- **Console and access (T01):** the console is part of the admin SPA at `/platform` on the root host. Its API is `/api/v1/platform/...`, which skips tenant resolution. Access needs four things (ADR 0010): platform staff, a 2FA-verified session, an address in `PLATFORM_IP_ALLOWLIST`, and no active impersonation.
  - The organisation list reads every tenant through the BYPASSRLS connection. It filters by status, plan, region, created and last activity, searches by name, slug or email, and sorts by name, created or last activity.
  - MRR is approximated from list prices (base fee plus billable tutors; annual / 12). Revenue share and custom contracts aren't included. Filtering by MRR is a follow-up.
  - The detail page shows the organisation, subscription, overrides, usage, members (verification, 2FA, last active), and recent failed webhooks, Billing events and messages. It also shows dead letters and the last 25 audit entries.
  - Integrations appear on the detail page when E23 builds them.
- **Tenant actions (T02):** six actions, each running in the organisation's tenant context through the owning app's services, so it lands in the organisation's audit log with the staff member as actor:
  - extend trial;
  - grant or remove entitlement overrides (a reason is required);
  - suspend or lift a suspension (back to trial or active, following the subscription);
  - set plan with a note (any plan, optionally activating a manually billed account);
  - resend owner verification and request a data export (`organisation.export_requested`, built by E28);
  - schedule deletion, which needs the subdomain typed and runs the E02 closure workflow.
  
  Plans can be edited at `/platform/plans` (name, description, visibility, trial days, entitlements, price amounts and Stripe price ids); the screen for it is a follow-up.
- **Flags (T03):** create a flag, then target it globally, by plan, by rollout % (stable per organisation), or with per-organisation overrides.
- **Operations (T04):** shows outbox pending and lag, dead letters (overall and by type), Celery queue depths, and payment and Billing webhook backlogs. Dead letters can be listed and replayed in bulk.
- **Support access (T05):** "View as" any member needs a reason (and ticket). It returns a single-use 5-minute link that signs the staff member in on the tenant's host and starts a read-only impersonation.
  - Owners and admins see every session, and holders of `support.access.view` get an in-app notice.
  - Owners can require a grant (`security.support_access_requires_grant`) and create time-limited grants. Write access only comes from a grant with `allow_write`.
  - Stopping the impersonation ends the session.
  - Deviation: grants are owner-only (`support.access.manage`); admins can view.
- **Observability (T06):** Sentry and OpenTelemetry already existed.
  - New metrics: a beat task writes outbox lag, dead letters, queue depth and webhook backlogs every minute in CloudWatch embedded metric format.
  - `monitoring.tf` adds paging and alert SNS topics and SLO alarms: API 5xx > 1%, p95 latency, unhealthy web tasks, outbox lag > 60s, dead letters, webhook backlogs, queue depth, RDS CPU and storage. It also adds a dashboard.
  - An outage banner comes from platform notices (`GET /api/v1/status`, posted from Operations) in the admin and portal apps, with a link to `STATUS_PAGE_URL`. The external status page provider (e.g. Instatus) is configured outside the code.
- **Backups and DR (T07):** RDS has 35-day PITR. AWS Backup takes daily snapshots of RDS and the uploads bucket and copies them to the backup account's vault (365 days). `manage.py tenant_dump <slug>` writes one organisation's rows from a point-in-time copy. The runbooks in `docs/runbooks/` cover deploy, rollback, database restore, single-organisation restore, alerts, provider outage, incident comms and the quarterly drill.
  - Deviation: daily *logical* (pg_dump) exports are replaced by cross-account snapshot copies.
- **Follow-ups:** a plans and prices screen; integration status on tenant detail (E23); Temporal-specific alarms (workflow task failures); a status page provider integration; Part 2 (T08–T10).

## Part 2 implementation notes (as built 2026-10-14)
ADR 0030 records the main decisions. Tenant-facing parts are in a new `success` app; parts that span organisations are in `platform_admin`, which is still the only app that may use the BYPASSRLS connection.

- **Help panel (T08):** the admin shell has a **Help** button (a dot shows unread "What's new" entries and support replies). It opens a side panel (`<dialog>`: focus moves in, Escape closes it, focus returns to the button) with five tabs: articles, What's new, tours, chat with support and usage data.
  - Articles are markdown files in the repository (`success/help/<locale>/*.md`, en-GB fallback) with front matter (title, summary, routes, tags, tour). An in-process index searches them; every word must match, and titles rank above tags, summaries and body text. With no search words, the panel suggests the articles for the current page. The frontend renders a safe markdown subset (headings, lists, bold, same-site or https links) as React elements.
  - "What's new" entries are files in `success/help/changelog/`. Opening the tab marks them as read (`GuidanceState.changelog_seen_at`).
  - API: `/help/articles` (`?q=&route=`), `/help/articles/{slug}`, `/help/changelog`, `/help/changelog/seen` and `/me/guidance`.
  - Deviation: no headless CMS or Intercom/Help Scout. Content is reviewed like code and can be moved to a CMS later behind `success.help`.
- **Product tours (T08):** `Tour` is a non-modal dialog. It moves focus to each step's heading, announces "Step n of m", closes on Escape and returns focus to where the person was. It outlines the step's element and scrolls it into view (no smooth scrolling when reduced motion is preferred). A step whose element is not on the page is shown without a highlight.
  - There are three tours: welcome, calendar and billing. New staff are offered the welcome tour once on the dashboard. Finished and dismissed tours are stored per person (`/me/guidance/tours/{key}`).
- **Setup checklist (T08):** the dashboard card has five steps: set up a service, add a student, schedule a lesson, connect Stripe and send the first invoice. It has a progress bar and links to the steps still to do.
  - Steps tick themselves from domain events (`service.created`, `student.created`, `lesson.scheduled`, `provider_account.connected`, `invoice.issued`/`invoice.sent`), idempotently (unique per organisation and key). Steps already done when the checklist is first opened are found from existing data.
  - Events: `setup_checklist.item_completed`, then `setup_checklist.completed`. Holders of `success.checklist.manage` (owners and admins) can hide the checklist.
  - Deviations: "connect Stripe" counts any connected payment provider. The E02 onboarding wizard (`onboarding.*` events) is unchanged; the checklist is the after-signup guide.
- **Support chat (T08):** built-in messaging between an organisation's staff and TutorTrack support (`SupportConversation`/`SupportMessage`, tenant data with RLS). No third-party widget.
  - Staff with `success.support.chat` open conversations from the help panel. The conversation records the page as a route pattern. Coordinators and finance have the `own` scope; owners and admins see every conversation in their organisation.
  - Platform staff answer at `/platform/support` (inbox across organisations: unread, open, answered and closed). Replies, assignment and closing run in the organisation's tenant context through `success.services`, so they appear in the organisation's audit log with the staff member as the actor.
  - The person who asked can rate an answered chat (CSAT 1-5).
  - Deviation: E13 inbox threads were not reused, because they belong to an organisation's families and contacts and run on comms channels. Support replies are shown as a dot on the Help button, not as a comms notification.
- **Product analytics (T09):** first-party capture to `POST /analytics/events`, with no third-party SDK. Nothing is recorded unless four conditions are all met:
  1. The person chose analytics in the E29 cookie banner, or with the "Share anonymous usage data" switch in the help panel. Both write the same `tt_consent` cookie, and the browser sends nothing without it.
  2. The organisation allows it (new setting `privacy.product_analytics`, default on).
  3. The person is staff. Families and students are never tracked (AADC: no profiling of children).
  4. Support is not viewing as the person.
  - Events are pseudonymous. The actor is a keyed hash of the organisation and user, and routes are patterns with ids replaced by `$id`. Properties are short scalars: the filter drops keys such as name, email and phone, and values that look like emails, phone numbers, UUIDs, tokens or free text.
  - Sinks are the provider seam (`PRODUCT_ANALYTICS_SINKS`). The default `DatabaseSink` stores `ProductEvent` rows; an exporter for PostHog or Segment would be another sink.
  - E29 registry: DSAR export includes a count of a person's events, erasure deletes them, and a new retention category `product_usage` (395 days) purges old ones.
  - The console's "Feedback and usage" page shows top events and pages, and an onboarding funnel built from setup checklists.
  - Deviation: the cookie banner itself still appears only on public pages (E29). Inside the admin app, consent is given in the help panel.
- **Tenant health (T09):** the platform Temporal Schedule `schedule:platform-insights:platform` (03:30 UTC) runs `PlatformInsightsWorkflow` on the `default` queue, with no sweeper columns.
  1. A platform activity lists the organisations that are not cancelled.
  2. Batches of 25 organisations are scored, each in its own tenant context.
  3. Platform staff get one email about organisations that became at risk (`alerted_at`, at most once per organisation and day).
  - Each organisation gets a `TenantHealthScore` per day. Its components (0-100) are usage depth, active tutor trend, payments trend, reliability (failed messages, webhooks and dead letters), support conversations and NPS, weighted 30/20/20/10/10/10. A component with no data is left out and the others are rescaled. Risk is healthy (70+), watch (40-69) or at risk (under 40).
  - The console has a health worklist (lowest scores first, filter by risk, "Recalculate now"), risk counts and a health card on the organisation page.
  - The schedule is created by `manage.py ensure_platform_schedules`, which the Temporal worker runs before it starts polling (docker-compose and `ecs.tf`). It uses the new `core.workflows.schedules.ensure_platform_schedule` helper (no `ScheduleLink`, so suspending an organisation never pauses it).
  - Deviation: the scores, snapshots and alerts are computed facts, so they aren't written to the audit log.
- **NPS/CSAT (T09):** a non-modal corner prompt (radio group 0-10 and an optional comment). It never takes focus.
  - It appears for staff who joined at least 14 days ago, at most every 90 days, and rests for 30 days after "Not now". Organisations can turn it off (`privacy.satisfaction_surveys`).
  - Answers are `SurveyResponse` rows (`survey.answered`). The console shows NPS, promoters, passives and detractors, NPS by plan and by month, recent comments (organisation and role, never the respondent) and the support CSAT average.
- **SaaS metrics (T10):** the same nightly run snapshots each organisation's subscription (`SubscriptionSnapshot`: plan, status, seats, MRR). MRR is calculated from E04 list prices: the base fee, active tutors and extra branches above the included quantity, with annual prices divided by 12 and rounded half-up with `core.money`. `/platform/metrics` derives everything from month-end snapshots, one billing currency at a time:
  - MRR, ARR, paying customers, ARPA, customers in trial and MRR past due (dunning oversight);
  - MRR movements: new, reactivation, expansion, contraction and churn, with `end = start + net new` (a Hypothesis test checks it);
  - customer and revenue churn and NRR;
  - trial conversion by sign-up month;
  - cohort retention by first paying month (customers and revenue).
  
  The maths is in `platform_admin.metrics`, with Hypothesis tests for MRR rounding, movements, ARPA, trial conversion and the health score bounds.
  - Deviations:
    - Revenue share (a percentage of payments) is not counted in MRR, and revenue-share reconciliation is a follow-up.
    - Currencies are never converted.
    - History starts with the first nightly run; there is no backfill from Stripe.
    - A closed organisation's snapshots are deleted with it, after the E02 retention period.
    - The Part 1 tenant list still shows its list-price MRR estimate.
- **Shared files touched:**
  - `config/settings/base.py`: `INSTALLED_APPS` gets `tutortrack.success`, and two `ENUM_NAME_OVERRIDES`;
  - `config/urls.py`;
  - `identity/roles.py`: `success.support.chat:own` for coordinator and finance;
  - `core/workflows/schedules.py`: `ensure_platform_schedule`;
  - frontend: `AppShell.tsx` (one `<SuccessLayer />`), `HomePage.tsx`, `router.tsx`, and `PlatformShell`/`TenantPage`;
  - `docker-compose.yml` and `infra/terraform/ecs.tf` (the worker command).
  
  The new i18n namespaces are `help`, `tours`, `setupChecklist`, `nps`, `supportChat`, `productAnalytics`, `tenantHealth`, `saasMetrics`, `productInsights` and `supportInbox`.
- **Follow-ups:** support reply notifications through comms (email and push), a CMS for help content, translated help articles, an exporter sink for an external analytics tool, revenue-share MRR and reconciliation, and MRR filters on the tenant list.

## Gap backlog (as built 2026-10-14)

Batch G6 of `docs/05-gap-backlog.md`; design in ADR 0034.


- **Plans and prices screen (FR-30-1; E30:72):** `/platform/plans` edits name, description,
  visibility and trial days, and each price's amount, included quantity and Stripe price ID
  per currency (the API already existed).
- **Tenant pages (FR-30-1; E30:86, E30:151):** the tenant list filters and sorts by MRR from the
  latest nightly snapshot (`mrr_min`, `mrr_max`, `currency`, `ordering=-latest_mrr`;
  `snapshot_mrr` on each row); tenant detail shows integration connections (provider, level,
  status, count, last sync, failed accounting syncs; no secrets) and active add-ons.
- **Support reply notifications (FR-30-5; E30:151):** a reply from support notifies the person
  who opened the conversation by in-app, email and Web Push (`support_reply`, hidden and
  transactional, deduplicated per message); the link `/?support=<id>` opens the chat.
- **Revenue-share MRR and reconciliation (FR-30-7; E30:137, E30:151):** snapshots add
  `revenue_share_mrr` (share × metered payments of the last 30 days, half-up, Hypothesis
  test) into MRR. `/platform/revenue-share?month=` compares payments processed (recomputed per
  day) with what was reported to the Stripe meter per organisation, lists unreported and
  changed days, and `report-missing` reports the unreported days (audited). Deviation:
  refunds after a day was reported are shown for a manual credit, not sent (meter events
  can't be negative).
- **Customer notices** and the **workflow console** are listed under E29 and E32.
