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
- [ ] **E30-T01** Platform staff auth hardening, `/platform` area, tenant list/detail.
- [ ] **E30-T02** Tenant actions (trial extend, overrides, suspend, plan change) with audit.
- [ ] **E30-T03** Feature flag management UI with targeting.
- [ ] **E30-T04** Outbox/dead-letter/queue monitoring views and replay.
- [ ] **E30-T05** Support impersonation with tenant-granted access and tenant-visible audit.
- [ ] **E30-T06** Observability dashboards, SLO alerts, status page and outage banner.
- [ ] **E30-T07** Backup/restore drills and per-tenant restore tool; runbooks.
- [ ] **E30-T08** (Scale) Help panel, product tours, onboarding checklist, support chat.
- [ ] **E30-T09** (Scale) Product analytics, tenant health scoring, NPS.
- [ ] **E30-T10** (Scale) SaaS metrics dashboards.
