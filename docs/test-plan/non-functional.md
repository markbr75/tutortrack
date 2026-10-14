# Non-functional checks

These are spot checks for performance, security, recovery, observability, data protection, resilience and locale. They don't replace the automated suites (`make check`, the security scans in CI and `docs/security/asvs.md`). They catch what needs a human eye before a release. Use the README's environments and seeded accounts. Record results as described in [README.md](README.md).

- **Performance budgets** are smoke-level on a developer machine with the seed data. Production budgets and alarms live in `docs/runbooks/alerts.md` (for example p95 above 1.5 s pages).
- **Security cases** that are features in their own right (MFA, passkeys, DSAR, safeguarding, retention) are in [E03](E03-identity-access.md) and [E29](E29-security-privacy-compliance.md). This file holds the cross-cutting checks.

## Performance smoke

| ID | Title | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|
| TP-NF-001 | Admin app first load | 1. Clear the cache; open http://brightminds.localhost:5173/ signed in (production build via `vite preview`).<br>2. Read DevTools → Network and Performance (LCP). | Home is usable within 3 s on a normal laptop; no request takes more than 1 s; no console errors. | P2 | No | |
| TP-NF-002 | Portal on a mid-range phone | 1. Lighthouse mobile on `/portal/` and `/portal/tutor` (built portal). | Performance ≥ 90; JS payload small enough (see TP-E15-049, TP-E16-046). | P2 | No | |
| TP-NF-003 | List endpoints with seed data | 1. In DevTools, open `/clients`, `/students`, `/jobs`, `/billing`, `/leads` five times each and note the API timings. | Each list API answers in under 500 ms (p95 of the five); cursor pagination, no `count(*)` storms in the Django log. | P2 | No | |
| TP-NF-004 | Calendar month view | 1. Open `/calendar` → Month with all tutors.<br>2. Switch Week, Agenda, Tutors. | Each view renders in under 1 s; the range is limited (TP-E08-027). | P2 | No | |
| TP-NF-005 | A year of weekly lessons | 1. Create a weekly series for 52 weeks (TP-E08-013). | It saves in a few seconds and the calendar stays responsive. | P3 | backend: `tutortrack/scheduling/tests` | |
| TP-NF-006 | Invoice run of many lessons | 1. Complete 200+ lessons (import or API).<br>2. Run the monthly invoice run (TP-E10-011). | The run finishes in under a minute; the UI shows progress, not a timeout; totals reconcile. | P2 | No | |
| TP-NF-007 | Reporting dashboards | 1. Open `/` and `/analytics` reports with a 12-month range. | Under 2 s per widget; facts rebuild with `rebuild_reporting_facts` in seconds on seed data. | P3 | No | |
| TP-NF-008 | Large import | 1. `cd backend && PERF_TESTS=1 uv run pytest tutortrack/migration/tests/test_imports.py -k five_thousand` (5,000 students). | Passes within its budget (TP-E28-018). Run on a quiet machine; CI skips it. | P3 | backend: `tutortrack/migration/tests/test_imports.py` (PERF_TESTS=1) | |

## Security spot checks

| ID | Title | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|
| TP-NF-010 | Sign-in protections | 1. Wrong password several times (TP-E03-003, TP-E03-004).<br>2. Check the responses for an unknown email. | Same message for both; progressive lockout; no user enumeration. | P1 | e2e: `e2e/roles.spec.ts`; backend | |
| TP-NF-011 | MFA and passkeys | 1. Turn on TOTP, sign in, use a recovery code, add a passkey (TP-E03-016…025).<br>2. Enforce 2FA for staff (TP-E03-020). | Works end to end; staff can't skip enforcement; portal users unaffected. | P1 | backend | |
| TP-NF-012 | Sessions and remember me | 1. Sign in with and without "remember me"; close the browser.<br>2. Leave a staff session idle past `SESSION_IDLE_TIMEOUT_HOURS` (8 h, or a shorter org setting).<br>3. Revoke a session from `/account` (TP-E03-014). | Cookie is HttpOnly and SameSite=Lax (and Secure over HTTPS); remember me lasts 30 days; idle staff sessions end; a revoked session is signed out at its next request. | P1 | backend | |
| TP-NF-013 | Rate limits | 1. Exceed each limit with a script: sign-in 30/min, 2FA 20/min, magic link 10/h, password reset 10/h, signup 10/h, public form 20/h, public widget 600/h; public API key limits (TP-E27-017, TP-E27-018). | HTTP 429 with an RFC 7807 body and `Retry-After`; normal use unaffected. | P1 | backend | |
| TP-NF-014 | CSRF | 1. Signed in, send a POST to `/api/v1/clients/quick-add` without the `X-CSRFToken` header (curl with the session cookie).<br>2. Send one from another origin. | Refused with 403; the app's own requests work. | P1 | No | |
| TP-NF-015 | Signed links expire and work once | 1. For each link type, use it, then use it again, then tamper with one character, then wait past its expiry (or shorten it in settings): `/pay/<token>`, `/pay/setup/<token>`, `/feedback/<token>`, `/proposals/<token>`, `/shortlists/<token>`, `/review/<token>`, `/re-enrol/<token>`, `/offers/<token>`, `/interviews/<token>`, `/references/<token>`, magic links (15 min) and password reset (1 h).<br>2. Open a Bright Minds link on the Northside host. | Single-use links refuse a second use; tampered and expired links show a friendly "no longer valid" page with no data; links never work on another organisation's host. | P1 | backend (per epic) | |
| TP-NF-016 | API key scopes | 1. Use the read-only demo key to POST (TP-E27-003).<br>2. Use a key whose creator has left (TP-E27-013).<br>3. Use a key on internal endpoints (TP-E27-005). | Refused; scopes never widen the creator's role. | P1 | backend | |
| TP-NF-017 | SSRF guard | 1. Try private, loopback, link-local and metadata URLs (`http://127.0.0.1`, `http://169.254.169.254`, `http://10.0.0.1`, a DNS name resolving to 127.0.0.1, an `http://` URL) as: a webhook endpoint (TP-E27-022), an automation webhook action (TP-E14-010), an import URL (Google Sheets), a CalDAV server, a resource link (TP-E21-002), a website block image. | All refused with a clear message; nothing is fetched (check the backend log). | P1 | backend: `tutortrack/core/tests` | |
| TP-NF-018 | File uploads | 1. Upload a file over the 25 MB limit, a disallowed type (`.exe`, `.html`, `.svg` with a script), a file with a double extension.<br>2. With `docker compose --profile clamav up -d clamav` and `CLAMAV_ENABLED=true`, upload the EICAR test file (TP-E01-031). | Oversize and disallowed types refused; EICAR quarantined; nothing executable is served inline. | P1 | backend | |
| TP-NF-019 | Presigned downloads | 1. Copy a document download URL; open it after 15 minutes.<br>2. Open it signed in as Northside (TP-E01-032). | Expired after 900 s; another tenant's file is never served. | P2 | backend | |
| TP-NF-020 | XSS in rich text and names | 1. Enter `<img src=x onerror=alert(1)>` and `<script>` in a note, a family name, a report field, a broadcast body, a website block, an enquiry form answer and a review text. | Shown as text or sanitised; no script runs in the admin app, the portal, emails, PDFs or the hosted site (TP-E05-027, TP-E24-037). | P1 | backend (nh3 sanitiser) | |
| TP-NF-021 | IDOR across tenants | 1. As Bright Minds staff, call detail endpoints with Northside IDs (client, invoice, lesson, document, report, conversation) (TP-E02-046). | 404 every time; no data or names leak in the error. | P1 | e2e: `e2e/roles.spec.ts`; backend `TenantIsolationTestMixin` | |
| TP-NF-022 | Security headers and CSP | 1. `curl -I` the API, a Django page and the built admin app; check `Content-Security-Policy`, `Strict-Transport-Security` (HTTPS only), `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` / `frame-ancestors` (TP-E01-046, TP-E29-001). | Present and strict; widgets are embeddable only from configured origins. | P2 | backend | |
| TP-NF-023 | Sensitive reads are audited | 1. View a tutor's bank details, a student's medical notes and a safeguarding case. | Each read is recorded (`audit.record_read`); safeguarding access appears only in the case's own log (TP-E29-010, TP-E29-048). | P1 | backend | |
| TP-NF-024 | Secrets shown once | 1. Create an API key, a webhook secret, an OAuth client secret and TOTP. | Shown once; never in logs, the audit diff or later API responses. | P2 | backend | |
| TP-NF-025 | Dependency and code scans | 1. Check the latest CI run: gitleaks, Semgrep, pip-audit/npm audit (or the jobs that exist). | No new high findings. | P2 | CI | |

## Backup and restore (runbook dry run)

Runbooks live in `docs/runbooks/`: `backup-drill.md`, `database-restore.md`, `restore-one-organisation.md`, `rollback.md`, `deploy.md`, `provider-outage.md`, `incident-comms.md` and `alerts.md`.

| ID | Title | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|
| TP-NF-030 | Quarterly restore drill (dry run) | 1. Walk through `docs/runbooks/backup-drill.md` against staging, or locally: `pg_dump` the dev database, restore into a scratch database, run `manage.py check --database default`, compare row counts. | Every step can be followed as written; the time is recorded in the drill log; target RTO ≤ 4 hours. | P2 | No | |
| TP-NF-031 | Restore one organisation | 1. Follow `docs/runbooks/restore-one-organisation.md`; locally run `uv run python manage.py tenant_dump brightminds` against a scratch copy. | The dump contains only that organisation; the steps are accurate. | P2 | No | |
| TP-NF-032 | Full database restore steps | 1. Read through `docs/runbooks/database-restore.md` with an engineer: incident notice, scaling `worker`, `beat` and `temporal-worker` to 0, point-in-time restore. | No missing steps or wrong commands; notice posted from the console works (TP-E30-018). | P3 | No | |
| TP-NF-033 | Release rollback | 1. Read through `docs/runbooks/rollback.md`; locally run the previous build against the current database. | The old build still works (backward-compatible migrations); workflow rollback guidance is clear. | P3 | No | |

## Observability

| ID | Title | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|
| TP-NF-040 | Health and readiness | 1. `curl http://localhost:8010/healthz` and `/readyz`.<br>2. Stop Redis; call `/readyz` again. | `/healthz` is ok while the process runs; `/readyz` reports each dependency and fails when one is down (TP-E01-007, TP-E01-008). | P1 | e2e: `e2e/smoke.spec.ts` (`/healthz`) | |
| TP-NF-041 | Structured logs without PII | 1. Set `LOG_JSON=true`; sign in, add a family, take a payment, send an email.<br>2. Read the logs. | JSON lines with request ID and organisation ID; no names, emails, phone numbers, tokens or card data (TP-E01-045, TP-E13-055). | P1 | backend | |
| TP-NF-042 | Error reporting | 1. Set `SENTRY_DSN` to a test project; trigger a 500 (for example a temporary bad setting). | One event with the request ID, release and organisation tag; no PII in the payload. | P3 | No | |
| TP-NF-043 | Tracing | 1. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to a local collector (for example Jaeger); load a page. | Traces show the request, database and Redis spans. | P3 | No | |
| TP-NF-044 | Workflows and background jobs visible | 1. Start an invoice run and a broadcast.<br>2. Find them in the Temporal UI by `OrganisationId` (TP-E32-003); watch the Celery worker log. | Each process is findable; failures show the activity error; the platform console's Operations page shows outbox lag and dead letters (TP-E30-016). | P2 | No | |

## Data protection

| ID | Title | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|
| TP-NF-050 | Encrypted fields at rest | 1. Save a tutor's bank details, a TOTP secret, an OAuth token and a safeguarding note.<br>2. Read the rows with `psql`. | The columns hold ciphertext, never plain text (TP-E29-004). | P1 | backend | |
| TP-NF-051 | Key rotation | 1. `uv run python manage.py generate_encryption_key`; put the new key first in `FIELD_ENCRYPTION_KEYS`.<br>2. `uv run python manage.py rotate_encryption_keys`.<br>3. Remove the old key; read the records in the app. | Everything still decrypts; nothing is left on the old key. | P2 | backend | |
| TP-NF-052 | Row-level security | 1. Connect with the app role (`DATABASE_URL`) in `psql` without setting a tenant; `select count(*) from people_client`. | Zero rows (TP-E01-043); only the platform role bypasses RLS. | P1 | backend | |

## Resilience

| ID | Title | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|
| TP-NF-060 | Celery worker down | 1. Stop the worker; complete a lesson and issue an invoice.<br>2. Start the worker. | Events wait in the outbox, then run once; nothing is lost or doubled (TP-E01-019). | P1 | backend | |
| TP-NF-061 | Temporal worker restart | 1. Start a long process (a broadcast or invoice run); kill `temporal_worker` mid-run; start it again. | The workflow continues from where it stopped; no duplicate emails or invoices (TP-E32-016). | P1 | backend (replay tests) | |
| TP-NF-062 | Temporal server down | 1. Stop the Temporal container; do something that starts a workflow (send a proposal). | The request succeeds or fails cleanly; the start is retried once Temporal is back (see `docs/runbooks/provider-outage.md`). | P2 | No | |
| TP-NF-063 | Redis down | 1. Stop Redis; load the app. | Clear error or degraded mode; `/readyz` fails; recovery is automatic when Redis returns. Sessions use the cache backend, so users may need to sign in again. | P2 | No | |
| TP-NF-064 | Provider outages (fakes) | 1. `fail("google", 3)` (calendar), `fail("xero", 2)` (accounting), a Twilio status failure. | Retries with back-off, then a readable error and "Retry now"; other features unaffected. | P2 | backend | |

## Locale, time zones and currency

| ID | Title | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|
| TP-NF-070 | en-GB vs en-US | 1. Switch your profile locale to en-US (TP-E03-062); view dates, money, the calendar week start and spelling. | US formats (MM/DD, "color" only where en-US overrides); no hard-coded "£" or date strings. | P2 | No | |
| TP-NF-071 | Currency follows the organisation | 1. Sign up a US organisation (USD) and an organisation in a zero-decimal currency if supported; create services and invoices. | Currency symbol and decimals follow the organisation; money is never shown as a float (TP-E01-041, TP-E06-049). | P2 | No | |
| TP-NF-072 | Time zone and DST | 1. Create a weekly lesson at 16:30 London across the last Sunday of October and March (TP-E01-042, TP-E08-005).<br>2. View it as a user in America/New_York. | Lessons stay at 16:30 London time; the viewer sees their own time with the zone shown (TP-E08-067). | P1 | backend (Hypothesis) | |
| TP-NF-073 | Untranslated strings | 1. Browse the main screens with a pseudo-locale or en-US. | No raw i18n keys (`people.quickAdd.title`) or untranslated English hard-coded outside the locale files. | P3 | No | |
