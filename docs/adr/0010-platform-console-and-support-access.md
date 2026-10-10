# ADR 0010: Platform console outside tenancy, support access by hand-off link, metrics as logs

- **Status:** Accepted
- **Date:** 2026-10-10
- **Epic:** E30

## Context
TutorTrack staff need one console across every organisation (tenants, plans, flags,
dead letters) while row-level security keeps tenants apart everywhere else. Support must
sometimes see exactly what a customer sees, but customers must be able to trust and audit
that. Operations need alarms on application signals (outbox lag, webhook backlogs) without
adding an agent or a metrics client to every process.

## Decision
1. **`/api/v1/platform/...` skips tenant resolution** (like `/webhooks/`). Access needs
   `is_platform_staff`, a session that passed 2FA (`UserSession.mfa_verified`), an address in
   `PLATFORM_IP_ALLOWLIST`, and no active impersonation. Only cross-organisation lists read
   through the BYPASSRLS `platform` connection; that use stays confined to `platform_admin`
   (enforced by `core.tests.test_rls`). Everything about one organisation, reads and
   actions alike, runs inside that organisation's tenant context and through the owning
   app's services. The organisation's audit log therefore records what staff did.
2. **Support access is the existing impersonation, started by a single-use link.** The
   console records a `SupportSession` (reason and ticket required) and returns
   `https://<slug>.../api/v1/support/enter?token=…`. The link is valid for 5 minutes, used
   once and stored only as a hash. It signs the staff member in on the tenant's host (cookies
   don't span hosts in every environment) and starts a read-only impersonation. Owners are
   notified, can list every session, can require a grant before support may look
   (`security.support_access_requires_grant`), and only a grant with `allow_write` permits
   changes.
3. **Feature flags gain percentage rollout**, bucketed by a hash of flag and organisation, so
   raising the percentage only adds organisations. Resolution order: org override > plan >
   rollout > global.
4. **Metrics as logs:** a beat task writes outbox lag, dead letters, queue depth and webhook
   backlogs every minute in CloudWatch embedded metric format. Alarms treat missing data as
   breaching, so a stopped scheduler also pages.
5. **Outage banner:** `PlatformNotice` rows (platform data) served by the public
   `GET /api/v1/status` and shown by every app.

## Consequences
- The console is part of the admin SPA (`/platform`) on the root host, signed in like
  any user; there is no second login system.
- Restoring one organisation is a dump (`manage.py tenant_dump`) from a point-in-time copy,
  then re-creating records through services; there is no automated merge.
