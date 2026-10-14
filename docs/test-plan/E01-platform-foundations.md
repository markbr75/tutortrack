# E01 — Platform foundations: manual tests

**Scope.** The local stack, health checks, API conventions (RFC 7807 errors, cursor pagination, sparse fields, idempotency, ETags), the domain-event outbox, the audit log, file storage, sequence numbers, feature flags, the frontend shell and the seed. Most of E01 is infrastructure that backend tests cover well; these cases check what a human can see and the parts that only show up on a running stack. Spec: [E01](../epics/E01-platform-foundations.md).

**Built differently from the spec (Implementation notes win):** local S3 is SeaweedFS (not MinIO) on port 9010; host ports are Postgres 5442, Redis 6389, API 8010; uploads use presigned **PUT**; scan status is `skipped` when `CLAMAV_ENABLED=false` (local default); the seed is a registry of `seeds.py` steps, not a monolithic script, and creates one branch (not two) with 2 tutors and 3 families, not 5/20/30; the Terraform baseline is validated but not applied; Storybook is not built in CI.

**Common preconditions.** Stack running per [README](README.md) (`make infra` + backend on the host, or `make dev`), `make seed` run, Celery worker running for the outbox cases. Admin app: http://brightminds.localhost:5173. API docs: http://brightminds.localhost:5173/api/v1/docs/ (proxied). Password for all seeded accounts: `tutortrack` unless `SEED_ADMIN_PASSWORD` is set.

## Local environment and seed

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-001 | Fresh stack gives a working sign-in | Owner | Clean clone, `.env` copied from `.env.example` | 1. `make infra` (or `make dev`).<br>2. Run backend setup commands from CLAUDE.md.<br>3. `make seed`.<br>4. Open http://brightminds.localhost:5173 and sign in as admin@tutortrack.localhost. | Sign-in succeeds; the **Welcome** home page and the **Main** navigation show. | P1 | e2e: `e2e/smoke.spec.ts` | |
| TP-E01-002 | Seed is idempotent | Tester | Seed already run once | 1. Run `make seed` a second time.<br>2. Open Clients, Tutors, Jobs, Catalogue. | Command ends "Done (N steps)." with no error; no duplicate families, tutors, services, jobs or reviews. | P1 | backend: `tutortrack/core/tests/test_seed_and_storage_cli.py` | |
| TP-E01-003 | Seed refuses when DEBUG is off | Tester | `DJANGO_DEBUG=false` in the shell | 1. Run `uv run python manage.py seed_demo`.<br>2. Repeat with `--force` on a throwaway DB only. | Without `--force`: "Refusing to seed with DEBUG off". With `--force`: seeds. | P3 | backend: `tutortrack/core/tests/test_seed_and_storage_cli.py` | |
| TP-E01-004 | Seed prints the demo API key once | Tester | Fresh DB | 1. Run `make seed` and read the output.<br>2. Run it again. | First run prints "API key for local testing (shown once): …"; second run does not print a new key. | P2 | No | |
| TP-E01-005 | Storage bucket command | Tester | SeaweedFS running on 9010 | 1. `uv run python manage.py ensure_storage_bucket` twice. | First run creates `tutortrack-local`; second reports it exists. No error. | P3 | backend: `tutortrack/core/tests/test_seed_and_storage_cli.py` | |
| TP-E01-006 | Every infra service is healthy | Tester | `make dev` | 1. `docker compose ps`. | postgres, redis, s3, temporal and backend show `healthy`; Mailpit UI opens on http://localhost:8025, Temporal UI on http://localhost:8233. | P2 | No | |

## Health, API docs and conventions

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-007 | Liveness endpoint | Anonymous | — | 1. Open http://localhost:8010/healthz. | 200 OK. | P1 | backend: `tutortrack/core/tests/test_api.py`; e2e: `e2e/smoke.spec.ts` | |
| TP-E01-008 | Readiness reports each dependency | Anonymous | — | 1. Open http://localhost:8010/readyz.<br>2. Stop Redis (`docker compose stop redis`) and reload.<br>3. Start Redis again. | Step 1: 200 with database, cache and storage OK. Step 2: 503 naming the failing dependency. Step 3: back to 200. | P2 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-009 | OpenAPI docs are served | Owner | Signed in | 1. Open `/api/v1/docs/` (Swagger) and `/api/v1/redoc/`.<br>2. Download `/api/v1/schema/`. | Both UIs load and list the API groups; the schema downloads as YAML. | P2 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-010 | Validation errors are Problem Details | Owner | Signed in; Swagger | 1. `POST /api/v1/clients/quick-add` with an empty body. | 400 with `application/problem+json`, `type`, `title`, `status` and per-field `errors`. | P2 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-011 | Not found and unauthenticated are Problem Details | Anonymous / Owner | — | 1. Signed out, `GET /api/v1/clients`.<br>2. Signed in, `GET /api/v1/clients/00000000-0000-0000-0000-000000000000`. | 1: 401/403 problem JSON. 2: 404 problem JSON. No HTML stack traces. | P2 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-012 | Request ID is returned and propagated | Owner | Browser dev tools | 1. Load any admin page and inspect an `/api/v1/` response.<br>2. Repeat a request with header `X-Request-ID: test-123` (curl). | Every response has `X-Request-ID`; the supplied value is echoed back. Error pages show "Reference: …" with that ID. | P3 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-013 | Cursor pagination and "Load more" | Coordinator | More than one page of records (create 30 tasks or use the audit log) | 1. Open **Audit log**.<br>2. Scroll to the bottom and press **Load more**. | Further rows load without duplicates; the API uses `cursor=` links, not page numbers. | P2 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-014 | Sparse fields and expand | Owner | Swagger | 1. `GET /api/v1/clients?fields=id,display_name`.<br>2. `GET /api/v1/jobs?expand=client` (or another documented expand). | 1: only the named fields return. 2: the related object is embedded. | P3 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-015 | Idempotency-Key replays the stored response | Finance | curl with session cookie and CSRF token | 1. Send a financial POST (e.g. record a payment, E10/E11) with `Idempotency-Key: k1`.<br>2. Repeat it exactly.<br>3. Repeat with the same key and a different body. | 2: same response, nothing created twice. 3: 422/409 "key reused with a different request". | P1 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-016 | ETag prevents lost updates | Owner | Two browser tabs on the same editable record that uses ETags (organisation settings) | 1. Save a change in tab A.<br>2. Save a different change in tab B without reloading. | Tab B gets a 412 / conflict message asking to reload; tab A's change is kept. | P3 | backend: `tutortrack/core/tests/test_api.py` | |
| TP-E01-017 | Money is serialised as amount + currency | Owner | Swagger | 1. `GET /api/v1/catalogue/services`. | Rates show as `{"amount": "45.0000", "currency": "GBP"}` (string amounts, never floats). | P2 | backend: `tutortrack/core/tests/test_money.py` | |

## Outbox, background jobs and sequences

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-018 | Domain events are dispatched by the worker | Coordinator | Celery worker running | 1. Create a task on a client (Notes & Tasks) assigned to admin@.<br>2. Check Mailpit / notifications for the assignee. | The assignment notification arrives within a few seconds (outbox dispatch p95 < 5 s). | P2 | backend: `tutortrack/core/tests/test_events.py` | |
| TP-E01-019 | No worker means events wait, not vanish | Coordinator | Stop the Celery worker | 1. Create a task as above.<br>2. Start the worker. | Nothing is sent while the worker is down; once started, the notification arrives exactly once. | P2 | backend: `tutortrack/core/tests/test_events.py` | |
| TP-E01-020 | Dead-lettered events are visible and replayable | Platform staff | Platform console; an event forced to fail (backend test hook or a subscriber raising) | 1. Open **/platform/operations**.<br>2. Find the dead-lettered event and replay it. | The event is listed with its error; replay re-dispatches it and the count drops. | P3 | backend: `tutortrack/core/tests/test_events.py` | |
| TP-E01-021 | Sequence numbers are gap-free and per organisation | Finance | Two invoices issued in brightminds, one in northside | 1. Issue two invoices in brightminds.<br>2. Issue one in northside. | Brightminds numbers run consecutively; northside starts its own sequence. A cancelled draft does not burn a number. | P1 | backend: `tutortrack/core/tests/test_sequences.py` | |
| TP-E01-022 | Job references use the sequence | Coordinator | — | 1. Create a job (E07). | Reference is `JOB-` followed by the next zero-padded number. | P3 | backend: `tutortrack/jobs/tests/test_jobs.py` | |

## Audit log

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-023 | Changes appear in the audit log with a diff | Owner | — | 1. Rename the Patel family's client display name.<br>2. Open **Audit log** and search "Patel". | An "update" entry shows who, when, the record and old → new values. | P1 | backend: `tutortrack/core/tests/test_audit.py` | |
| TP-E01-024 | Audit filters and CSV export | Owner | Several entries | 1. Filter by actor, action and date range (From/To).<br>2. Press **Export CSV**. | Filters narrow the list; the CSV downloads, cells starting with `=`, `+`, `-`, `@` are escaped; the export itself is audited. | P2 | backend: `tutortrack/core/tests/test_audit_search.py` | |
| TP-E01-025 | Sensitive fields are redacted in diffs | Owner | — | 1. Change a student's date of birth or an encrypted tax number.<br>2. Look at the audit entry. | The entry records that the field changed but shows a redacted value. | P1 | backend: `tutortrack/core/tests/test_audit.py` | |
| TP-E01-026 | Audit log cannot be altered | Tester | `psql` as the app role (`tutortrack_app`) | 1. `UPDATE core_auditentry SET action='x';`<br>2. `DELETE FROM core_auditentry;` | Both fail (trigger/privilege error). | P1 | backend: `tutortrack/core/tests/test_audit.py` | |
| TP-E01-027 | Audit log needs permission | Coordinator, Tutor | — | 1. Sign in as coordinator@; look for **Audit log** in the nav; open `/audit` directly.<br>2. Same as tutor@ (via the admin app). | No nav item; the page shows no data / a permission message; API returns 403. | P1 | backend: `tutortrack/core/tests/test_audit.py`; e2e: `e2e/roles.spec.ts` | |
| TP-E01-028 | Repeated exports alert the owners | Admin | office@ | 1. Export the audit CSV several times in a row. | Owners get a mass-export alert (email in Mailpit / notification). | P3 | backend: `tutortrack/core/tests/test_audit_search.py` | |

## File storage

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-029 | Upload and download a file | Owner | Any upload control (e.g. logo in onboarding branding or a lesson report attachment) | 1. Upload a small PNG.<br>2. Download/preview it. | Upload completes (presigned PUT to localhost:9010); download works via a short-lived presigned URL. | P1 | backend: `tutortrack/core/tests/test_files.py` | |
| TP-E01-030 | Disallowed type or size is refused | Owner | — | 1. Upload a `.exe` or a file over the size limit. | Clear validation message; nothing stored. | P2 | backend: `tutortrack/core/tests/test_files.py` | |
| TP-E01-031 | Infected files are quarantined | Tester | `docker compose --profile clamav up -d clamav`, `CLAMAV_ENABLED=true` | 1. Upload the EICAR test string as a `.txt`. | The upload is rejected and deleted; no download link. | P2 | backend: `tutortrack/core/tests/test_files.py` | |
| TP-E01-032 | Another organisation's file can't be downloaded | Owner (northside) | A file ID from brightminds | 1. Signed in on northside, request the brightminds file download URL. | 404; no presigned URL issued. | P1 | backend: `tutortrack/core/tests/test_files.py` | |

## Feature flags

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-033 | Home lists the enabled features | Owner | Seed flags (all globally off) | 1. Open Home. | "Enabled features" lists none or only those turned on; "No optional features are enabled yet." when none. | P3 | backend: `tutortrack/core/tests/test_flags.py` | |
| TP-E01-034 | Per-organisation override turns a feature on | Platform staff | admin@ with 2FA (console needs MFA) | 1. Open **/platform/flags**.<br>2. For `multi_branch`, **Turn on for** brightminds' organisation ID.<br>3. Reload Settings in brightminds (cache up to 60 s). | Branches section appears in Settings for brightminds only; northside is unchanged. | P2 | backend: `tutortrack/core/tests/test_flags.py` | |
| TP-E01-035 | Override with an expiry lapses | Platform staff | As above | 1. Add an override with an "until" date in the past or a few minutes ahead.<br>2. Wait for expiry and reload. | Feature turns off again after the expiry. | P3 | backend: `tutortrack/core/tests/test_flags.py` | |

## Frontend shell

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-036 | Unauthenticated users see sign-in | Anonymous | — | 1. Open http://brightminds.localhost:5173/. | The **Sign in** heading shows. | P1 | e2e: `e2e/smoke.spec.ts` | |
| TP-E01-037 | Unknown route shows "Page not found" | Owner | Signed in | 1. Open `/does-not-exist`. | "Page not found" inside the app shell, with navigation still working. | P3 | No | |
| TP-E01-038 | API failure shows an error with retry | Owner | Stop the backend | 1. Navigate to Clients.<br>2. Start the backend and press **Try again**. | "Something went wrong." with **Try again**; retry loads the list. | P2 | No | |
| TP-E01-039 | Theme follows tenant branding | Owner | Brand colour set (Settings or Website & branding) | 1. Change the brand colour.<br>2. Reload. | Primary buttons and accents use the new colour; contrast remains readable. | P3 | No | |
| TP-E01-040 | Storybook for the UI package | Developer | — | 1. `pnpm --dir frontend storybook`. | Storybook opens and renders the ui components without errors. | P3 | No | |

## i18n, time zones and money

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-041 | Money formats by locale, never as floats | Owner | brightminds (en-GB, GBP) | 1. Open Catalogue → Services. | "£45.00" style formatting; no hard-coded symbol for other currencies (check a service priced in EUR shows €). | P2 | backend: `tutortrack/core/tests/test_money.py` | |
| TP-E01-042 | Weekly series keeps local time across DST | Coordinator | A weekly 16:00 lesson series spanning the last Sunday of October | 1. Open the calendar for the weeks before and after the clock change. | Lessons stay at 16:00 Europe/London both sides of the change. | P1 | backend: `tutortrack/core/tests/test_time.py` | |

## Tenant isolation

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-043 | Raw SQL without a tenant sees nothing | Tester | `psql` as `tutortrack_app` | 1. `SELECT count(*) FROM people_client;` without setting `app.current_org`. | 0 rows. | P1 | backend: `tutortrack/core/tests/test_rls.py` | |
| TP-E01-044 | Raw SQL sees only the chosen tenant | Tester | As above | 1. `SELECT set_config('app.current_org', '<northside id>', false);`<br>2. `SELECT display_name FROM people_client;` | Only Northside's clients (e.g. the Northside family); no Patel/Okafor/Hughes. | P1 | backend: `tutortrack/core/tests/test_rls.py` | |

## Errors and edge cases

| ID | Title | Role | Preconditions / data | Steps | Expected result | Priority | Automated? | Result |
|---|---|---|---|---|---|---|---|---|
| TP-E01-045 | Logs carry no PII | Tester | Backend log output | 1. Sign in, create a family with an email and phone.<br>2. Read the backend logs. | Request IDs and org IDs present; emails, phone numbers, passwords and tokens are scrubbed. | P1 | backend: `tutortrack/core/tests/test_observability.py` | |
| TP-E01-046 | Security headers on API and HTML | Anonymous | curl `-I` | 1. `curl -I http://localhost:8010/api/v1/features`.<br>2. `curl -I` an HTML page (e.g. public site). | API: `X-Content-Type-Options: nosniff`, restrictive CSP. HTML: CSP with a nonce. | P2 | backend: `tutortrack/core/tests/test_security.py` | |
