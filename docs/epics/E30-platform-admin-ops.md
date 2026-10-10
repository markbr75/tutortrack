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
- [ ] **E30-T08** (Scale) Help panel, product tours, onboarding checklist, support chat.
- [ ] **E30-T09** (Scale) Product analytics, tenant health scoring, NPS.
- [ ] **E30-T10** (Scale) SaaS metrics dashboards.

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
