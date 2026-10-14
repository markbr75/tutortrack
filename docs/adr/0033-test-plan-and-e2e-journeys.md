# ADR 0033: A repo test plan and Playwright journeys against a seeded, production-like stack

- **Status:** Accepted
- **Date:** 2026-10-14
- **Scope:** `docs/test-plan/`, `frontend/e2e/`, the CI `e2e` job, the dev seed (`backend/tutortrack/identity/seeds.py`). Cross-cutting; no epic owns it.

## Context
Epics E01–E32 are built (the last Phase 3 tickets are being merged). Testers and the product
owner need one place that says how to check every feature by hand, and the most important
journeys need browser tests that run in CI. Until now the e2e job ran three smoke tests
against the admin app only: the portal was not served, the seed had a single sign-in (the
owner), there was no second organisation to prove tenant isolation in a browser, and the
backend in the job had no Temporal server, no Celery worker and production rate limits.

## Decision
1. **The manual plan lives in the repo as markdown** (`docs/test-plan/`): one file per
   epic with stable IDs (`TP-EXX-NNN`), priority and an "Automated?" column; cross-epic
   journeys, a WCAG 2.2 AA checklist, non-functional checks and a traceability matrix.
   It changes with the code in the same pull requests, and testers record results in the
   tables or a copied run folder.
2. **One seeded sign-in per role and a second organisation.** `identity/seeds.py` adds
   Admin, Branch Manager, Coordinator, Finance, Tutor (Nia Adeyemi), Parent (Priya Patel),
   Student (Arjun Patel), Affiliate (Hillside Primary PTA) and platform-staff accounts with
   the shared seed password, plus "Northside Learning" with one family. Manual testers and
   the specs use the same accounts.
3. **The portal shares the admin host locally, as in production.** The admin Vite dev and
   preview servers proxy `/portal` to the portal server (`PORTAL_DEV_URL`, default :5174),
   so password sign-in redirects, sessions and signed links behave as on a real tenant host.
4. **Specs own their data.** `e2e/fixtures.ts` signs in through the API once per role per
   worker (sign-in is rate limited) and creates families, tutors, jobs, lessons, classes and
   forms with unique names, so specs are independent, order-free and re-runnable on the
   same database. Times are fixed London times (10:00 yesterday, 17:00 next week) to avoid
   time-of-day flakiness; providers are the in-process fakes (PayPal for portal payments,
   the deterministic Claude fake for AI replies).
5. **The CI e2e job runs the journeys against the docker-compose backend** with Temporal
   started (workflows start; no worker is needed for the assertions),
   `CELERY_TASK_ALWAYS_EAGER=true` (domain events handled in-process, deterministic),
   `PLATFORM_REQUIRE_MFA=false` (the console without TOTP) and raised sign-in and
   public-form throttles. It builds both the admin app and the portal and serves them with
   `vite preview`.
6. **Accessibility is scanned automatically** with `@axe-core/playwright` (a dev
   dependency of the frontend workspace root) on eleven key screens, WCAG 2.0–2.2 A/AA
   tags, zero violations allowed. The manual checklist covers what axe cannot.

## Consequences
- The e2e folder is a workspace package (`@tutortrack/e2e`) so `pnpm -r lint` and
  `pnpm -r typecheck` cover it; ESLint turns off the React-hooks rule for Playwright's `use`.
- Writing the journeys surfaced and fixed three defects: payment provider return URLs,
  emailed tenant links and pay links ignored `TENANT_URL_TEMPLATE` and custom app domains
  (they now use `Organisation.base_url`); `/platform/me` reported 2FA missing when the
  deployment does not require it; and `runserver` leaked persistent database connections
  (development now defaults `DB_CONN_MAX_AGE` to 0).
- Eager Celery in the e2e job means asynchronous timing bugs between the API and workers
  are not caught there; backend tests and manual runs with a worker cover that.
- The specs accumulate data on a reused database; some pickers list the first 200 rows,
  so long-lived local e2e databases should be reset now and then (the README says how).
