# TutorTrack manual test plan

This plan lets testers, product owners and developers check every feature of TutorTrack by hand before a release. It also says which checks are automated. It covers epics E01–E32, including the Phase 2, 2b and 3 tickets, plus end-to-end business journeys, accessibility (WCAG 2.2 AA) and non-functional checks.

| File | What it covers |
|---|---|
| `E01-…md` to `E32-…md` | One file per epic: functional cases, permissions, tenant isolation, i18n/time zones/currency, errors and edge cases |
| [journeys.md](journeys.md) | End-to-end business journeys that cross epics (J01–J18) |
| [accessibility.md](accessibility.md) | WCAG 2.2 AA checklist per key screen |
| [non-functional.md](non-functional.md) | Performance smoke, security spot checks, backup/restore, observability, resilience |
| [traceability.md](traceability.md) | Epic → case IDs → automated coverage, and what needs real credentials |

## How to use the plan

- **Choose files by area.** For a release, run every P1 case in every file, then the journeys. For a change to one area, run that epic's file and the journeys that cross it ([traceability.md](traceability.md) shows which).
- **IDs.** `TP-EXX-NNN` is a case in epic XX (for example `TP-E10-014`). Cross-cutting files use `TP-J…` (journeys), `TP-A11Y-NNN` and `TP-NF-NNN`. IDs never change meaning; new cases are added at the end of a section with the next free number.
- **Priority.**
  - **P1:** must pass before a release. A P1 failure blocks the release.
  - **P2:** should pass. A failure needs a ticket and an agreed fix date.
  - **P3:** nice to check. Run when time allows or when the area changes.
- **Automated?** names the test that already covers the case: `backend: <file>` (relative to `backend/`, pytest) and/or `e2e: e2e/<spec>.spec.ts` (Playwright, in `frontend/`). "No" means manual only. Automated cases still deserve a human look at P1 before a release, because tests check behaviour, not how the screen looks or reads.
- **Phase 3 cases** (E12-T12, E16-T11, E18-T11, E22-T10, E23-T10, E26-T09) were checked against the merged build on 2026-10-14 (routes, labels, roles and the dev fakes they use). Where the build differs from the epic requirement, the case says what was built.
- **"Not built" items.** Where an epic's Implementation notes say a requirement was not built or was built differently, the case says so. Record such a case as N/A, not Fail.
- **Seed data.** Steps use the seeded records (the Patel family, tutor Nia Adeyemi, the GCSE Maths 1:1 service and so on). If a case changes shared seed data (for example it archives the Patel family), undo the change or reset the database afterwards.

## Environments

### A. Local development (host)

Follow `CLAUDE.md`:

1. `cp .env.example .env`, then `make infra`. This starts Postgres (5442), Redis (6389), SeaweedFS S3 (9010), Mailpit (8025) and the Temporal dev server (7233, UI 8233).
2. Backend: `cd backend && uv run python manage.py ensure_db_roles && uv run python manage.py migrate && uv run python manage.py ensure_storage_bucket && uv run python manage.py runserver 127.0.0.1:8010`
3. Background work (both are needed for most flows):
   - Celery: `cd backend && uv run celery -A config worker -l INFO` (add `-P solo` on Windows).
   - Temporal: `cd backend && uv run python manage.py temporal_worker --task-queue all`. Run `uv run python manage.py ensure_platform_schedules` once for the platform schedules.
4. Seed: `make seed` (see below).
5. Frontend: `pnpm --dir frontend install`, then:

| App | Command | URL |
|---|---|---|
| Admin app | `pnpm --dir frontend dev` | http://brightminds.localhost:5173 |
| Portal (families, students, tutors, affiliates) | `pnpm --dir frontend --filter @tutortrack/portal dev` (port 5174) | http://brightminds.localhost:5173/portal/ |
| Widgets playground | `pnpm --dir frontend --filter @tutortrack/widgets dev` | http://localhost:5175 |
| Hosted website | (served by Django) | http://brightminds.site.localhost:8010/ |
| Platform console | (admin app, root host) | http://localhost:5173/platform |
| API docs (Swagger) | (Django, proxied) | http://brightminds.localhost:5173/api/v1/docs/ |
| Mailpit (all email) | (`make infra`) | http://localhost:8025 |
| Temporal UI | (`make infra`) | http://localhost:8233 |

- **Portal URL.** The admin dev and preview servers proxy `/portal` to the portal server on :5174, so the portal is on the same origin as the admin app, as in production. Set `PORTAL_DEV_URL` to point the proxy somewhere else. You can also open http://brightminds.localhost:5174/portal/ directly; the session cookie is shared because cookies ignore the port.
- **Tenant = subdomain.** `brightminds.localhost` is Bright Minds Tutoring and `northside.localhost` is the second organisation. Browsers map `*.localhost` to your machine.
- **Platform console and 2FA.** `PLATFORM_REQUIRE_MFA` defaults to `true`, even in development. Either turn on TOTP for the platform account at `/account` first, or set `PLATFORM_REQUIRE_MFA=false` in `.env` and restart the backend. `PLATFORM_IP_ALLOWLIST` empty means any address.
- **Virus scanning** is off by default. To test it: `docker compose --profile clamav up -d clamav` and `CLAMAV_ENABLED=true`.

### B. Full stack in Docker

`make dev` starts everything with docker compose: `postgres`, `redis`, `s3`, `temporal`, `mailpit`, `backend` (http://localhost:8010), `worker` (Celery), `beat` (Celery beat), `temporal-worker` and `frontend` (admin dev server on :5173). Optional profiles: `--profile stripe` (Stripe CLI forwarding platform webhooks; needs real test keys) and `--profile clamav`. Run management commands with `docker compose exec backend uv run python manage.py <command>`. The compose `frontend` service runs only the admin app; start the portal on the host as in A if you need it.

## Loading and resetting data

- **Load:** `make seed` (or `cd backend && uv run python manage.py seed_demo`). It is idempotent, so running it twice changes nothing. It refuses to run when `DEBUG` is off unless you pass `--force` (never in production). It prints a read-only demo API key once; copy it for the E27 cases.
- **Reset:**
  - Compose stack: `docker compose down -v`, then `make dev` and `make seed`.
  - Host stack: stop the backend and workers, then `docker compose exec postgres psql -U tutortrack -d postgres -c "drop database tutortrack with (force)" -c "create database tutortrack owner tutortrack"`, then `ensure_db_roles`, `migrate`, `ensure_storage_bucket` and `seed_demo`.
- **Fast resets:** snapshot a freshly seeded database once with `docker compose exec postgres createdb -U tutortrack -T tutortrack tutortrack_seeded`, and restore with `drop database tutortrack` then `createdb -U tutortrack -T tutortrack_seeded tutortrack`. Stop the backend first, because a template copy needs no open connections.
- Restarting the backend clears fake-provider state held in memory (see below), so reset the database too if a case depends on it.

## Seeded accounts

All accounts use the password in `SEED_ADMIN_PASSWORD` (default **`tutortrack`**). The role accounts come from `backend/tutortrack/identity/seeds.py`.

| Role | Email | Linked to | Signs in at |
|---|---|---|---|
| Owner (and platform superuser) | `admin@tutortrack.localhost` | Bright Minds Tutoring; the only Designated Safeguarding Lead by default | http://brightminds.localhost:5173/login; platform console at http://localhost:5173/platform |
| Admin | `office@tutortrack.localhost` | Olivia Office | `/login` |
| Branch manager | `manager@tutortrack.localhost` | Marcus Manager, scoped to branch "Bright Minds Tutoring" (code MAIN) | `/login` |
| Coordinator | `coordinator@tutortrack.localhost` | Chloe Coordinator | `/login` |
| Finance | `finance@tutortrack.localhost` | Faisal Finance | `/login` |
| Tutor | `tutor@tutortrack.localhost` | Tutor profile Nia Adeyemi | `/login` (redirects to `/portal/tutor`) or the portal's emailed link |
| Parent (client contact) | `parent@tutortrack.localhost` | Priya Patel, The Patel Family | `/login` (redirects to `/portal/`) or the portal's emailed link |
| Student | `student@tutortrack.localhost` | Arjun Patel (Year 10) | `/login` (redirects to `/portal/`) or the emailed link |
| Affiliate / partner | `affiliate@tutortrack.localhost` | Affiliate "Hillside Primary PTA" | `/login`, then open http://brightminds.localhost:5173/portal/affiliate |
| Platform staff only | `platform@tutortrack.localhost` | No organisation | http://localhost:5173/login, then `/platform` |
| Other organisation's owner | `owner@northside.localhost` | Northside Learning (`northside`), family Olivia Northside with student Noah Northside | http://northside.localhost:5173/login |

- The portal sign-in page itself offers only an emailed sign-in link. Open the email in Mailpit and follow the link.
- Use Northside for every tenant-isolation case: nothing of Northside's may ever appear to Bright Minds users, and the reverse.
- The sign-in endpoint allows 30 attempts a minute per address. Wait a minute if you see "Too many requests".

### Key seed data (Bright Minds Tutoring, GB, GBP, Europe/London)

- **Families:** The Patel Family (Priya; Arjun, Year 10, GCSE Maths; Maya, Year 7, English), The Okafor Family (Tom; Ada, Year 12, Physics A level), Grace Hughes (adult learner).
- **Tutors:** Nia Adeyemi (active; Maths GCSE claimed, not yet approved) and Sam Clarke (Physics A level; onboarding). Matching needs approved subjects and active tutors (see E19).
- **Jobs and lessons:** Arjun's weekly GCSE Maths job with Nia (Tuesday 16:30) with planned lessons; Ada's job seeking a tutor. Nia and Sam are available Monday to Friday 15:00–20:00. A Christmas closure (24 Dec – 2 Jan).
- **Catalogue:** GCSE Maths 1:1 (£45/h charge, £28/h pay, 60 or 90 min), Piano lesson (£25 per lesson, 60% pay), 11+ group class (£20 per student per lesson, max 8); locations Leeds Centre and Online; Registration fee £30; package "10 hours of tuition" £420 (180 days).
- **Courses:** academic year, term "This term" with a half-term break, course "Year 6 11+ Prep" with the open class "Saturday 10am" (Years 5–6; no seeded student is eligible, so E20 adds one).
- **CRM and comms:** tags VIP and Exam year, a pinned note and a task on the Patel family; segment "Active families"; draft broadcast "Half-term timetable"; canned replies; inbox conversation "Thursday's lesson" from Priya.
- **Growth:** referral programme "Refer a friend"; three reviews of Nia (two approved, one pending); affiliate Hillside Primary PTA with the 10% "Standard partner rate".
- **Learning:** GCSE Maths and KS2 English curricula; resource "Equivalent fractions explained"; homework "Fractions worksheet"; goal "Grade 7 in GCSE Maths"; mock exam result; a revision guide on loan.
- **Other:** published website and brand kit; widgets "Tutor directory" and "Reviews"; a read-only API key; a DSAR (access) from Priya and default retention policies; AI features on (fake provider); setup checklist and a support conversation "Invoice runs"; today's health score and six months of subscription snapshots; reporting facts and FX rates.
- **No enquiry form** is seeded: E17 creates one (TP-E17-001).

### Features and plans

Features are gated by **plan entitlements**, not by the baseline feature flags (`multi_branch`, `payroll`, `pipeline`, `courses`, `ai_assistant`), which nothing checks. A new organisation starts a 30-day trial on the **Agency** plan (`TRIAL_PLAN=agency`), so almost everything is available. `white_label` and `custom_domain` need an override: in the platform console open the organisation and grant the entitlement, or use `/platform/flags` with "Turn on for" and the organisation ID. Changes can take up to 60 seconds to show.

### Settings without an admin screen

Some settings areas have no form. Change them with `PATCH /api/v1/settings/<area>` in Swagger while signed in, or in the Django shell. This applies to `billing`, `payroll`, `payments`, `portal`, `security`, `tutor_access` and others; the admin Settings page covers general settings, and delivery, leads, growth, AI and integrations have their own screens. Each epic file names the setting it needs.

## Fake providers in development

With the provider keys empty (the default), every external service is a fake. Fakes need no network. Their state lives in the backend process memory or in Redis, so **don't restart `runserver` in the middle of a flow**, and run a single backend process.

| Provider | How it behaves locally | How to trigger outcomes |
|---|---|---|
| Stripe Connect (E11) | "Connect Stripe" creates a restricted fake account; the onboarding link is a dead `connect.example.test` URL. The pay page loads real Stripe.js with a fake key, so **a card cannot be paid in the browser**. | POST to `http://localhost:8010/webhooks/stripe` with header `Stripe-Signature: fake-signature` and body `{"id":"evt_1","type":"…","account":"<acct>","data":{"object":{…}}}`. Activate the account with `account.updated` and `charges_enabled: true`. Simulate a card payment with `payment_intent.succeeded` (`id`, `amount`, `amount_received`, `currency`, `payment_method`, `metadata.invoice_id` or `metadata.payment_request_id`). Payment-method references containing `fail` are declined, `3ds` need authentication and `debit` stay pending. |
| Stripe Billing, our subscription (E04) | Checkout completes as soon as you return; charges succeed. | POST to `http://localhost:8010/webhooks/stripe/platform` with `Stripe-Signature: fake-signature` and `{"id":"evt_x","type":"invoice.payment_failed" or "invoice.paid","data":{"object":{"id":"in_x","customer":"<cus>","subscription":"<sub>"}}}`. Take the IDs from the `subscriptions_subscription` table. The Celery worker processes stored events. |
| GoCardless (E11) | Connect, the pay page and the setup link redirect straight back. Payments stay pending. | POST to `/webhooks/gocardless` with header `Webhook-Signature` = HMAC-SHA256 of the body with key `fake-gocardless-secret`. |
| PayPal (E11) | Connect and pay redirect straight back; the payment **captures immediately**. This is the easiest way for a parent to pay in the portal locally. | Webhooks: `/webhooks/paypal` with header `PAYPAL-TRANSMISSION-SIG: fake-signature`. |
| Twilio SMS and WhatsApp (E13) | Texts are recorded in the message log, not sent. | Inbound: POST form fields `From`, `To`, `Body` to `/webhooks/twilio/inbound` with `X-Twilio-Signature: fake-signature` (`STOP`/`START` opt out and in). Status: `/webhooks/twilio/status`. WhatsApp needs `TWILIO_WHATSAPP_FROM`. |
| Postmark (E13, E17) | Email goes to Mailpit. | Delivery and bounce webhooks: `/webhooks/postmark?token=<POSTMARK_WEBHOOK_TOKEN>` (refused while the token is empty). Inbox inbound email: `/webhooks/inbound/email?token=<COMMS_INBOUND_TOKEN>`, needs `COMMS_REPLY_DOMAIN`; addresses `inbox+brightminds@<domain>` or a thread's `reply+…` address. Enquiry inbound email: set `INBOUND_EMAIL_TOKEN=secret`, then POST `{"MailboxHash":"brightminds","FromFull":{"Email":"dee@example.com","Name":"Dee Jones"},"Subject":"…","TextBody":"…"}` to `/webhooks/inbound-email?token=secret`. |
| Web push (E16) | Without VAPID keys, `FakePush` records pushes. | For real browser push: `uv run python manage.py generate_vapid_keys` into `.env`. The service worker registers only in production builds, so test install, offline and push on the built portal (`vite preview` on :5174). |
| Calendars and video (E22): Google, Microsoft, CalDAV, Zoom, Lessonspace, Daily, Whereby | OAuth consents at once and returns to the app. CalDAV and Lessonspace accept any secret that doesn't contain "wrong". | In `uv run python manage.py shell`, inside `tenant_context(org)`: `from tutortrack.integrations.providers.fake import FakeCalendar, fail, revoke`; `FakeCalendar(conn.external_account_id).add_event(start, end, title="Dentist", busy=True)` (also `move_event`, `delete_event`); `fail("google", 2)` for outages; `revoke(account_id)` for a revoked grant. Then click "Sync now" (or wait up to 5 minutes; CalDAV polls every 10). Push endpoints: `/webhooks/google-calendar`, `/webhooks/microsoft-graph`. |
| Xero and QuickBooks (E23) | An in-memory fake ledger with a chart of accounts (090/091/092 bank, 200 sales, 404 fees, 820 VAT…), tax codes and a "Branch" tracking category. | `from tutortrack.accounting.providers.fake import FakeLedger, fail`; `FakeLedger(conn.external_account_id).records("invoices")`, `.archive("200")`, `.set_lock_date(date)`, `.record_payment(invoice_id, "20.00", "YYYY-MM-DD")` (read-back); `fail("xero", 1, auth=True)` for a revoked grant. |
| Custom domains (E24) | `CUSTOM_DOMAINS_DNS_RESOLVER=fake` with auto-verify; the fake certificate goes active at once. | Add a hosts-file entry (for example `www.brightminds.test`), add it to `DJANGO_ALLOWED_HOSTS` and browse on port 8010. Names under `.localhost` are refused. `GET /internal/tls/ask?domain=` answers ok or unknown. **Warning:** once an *app* domain is active, the organisation's links in emails switch to it; remove the domain after testing. |
| Mailchimp and Brevo (E13) | Fakes record the synced audience. | Connect with any key. |
| Geocoding (E05) | `GEOCODER=tutortrack.core.geo.FakeGeocoder` gives stable made-up points. | Save an address; the map shows it after the background task. |
| FX rates (E26) | A fixed fake table unless `FX_RATES_PROVIDER` is `ecb` or `oxr`. | `uv run python manage.py fetch_fx_rates`; `rebuild_reporting_facts` rebuilds report facts. |
| Claude API (E31) | With `ANTHROPIC_API_KEY` empty, a deterministic fake answers, plus a fake voice transcriber. Suggested replies start "Hi <name>, thanks for your message…"; "move … 5pm" is classified as Reschedule; the copilot answers "According to <report> [1]…". | Live evals: `AI_EVALS_LIVE=1 uv run python manage.py ai_evals --live` (needs a key). |
| Imports (E28) | TutorCruncher, Teachworks and Google Sheets fall back to fakes serving a sample agency; any non-empty key works. CSV presets for TutorBird, TutorCruncher and Teachworks. | No sample files ship: download templates from `/api/v1/import-templates/<entity>` or the template link on the Imports tab. |
| Outbound webhooks and URL fetches (E27, E14) | The SSRF guard allows only `https` URLs that resolve to public addresses. | Use a public HTTPS receiver (for example webhook.site; httpstat.us/500 for failures) or an HTTPS tunnel. This needs internet access. |
| Open Banking, payroll payouts, mileage | Fakes (Stripe payouts unless `PAYROLL_STRIPE_PAYOUTS`; mileage is straight-line × 1.25 without a Google key). | Run the flow in the app. |
| Cloudflare Turnstile | Skipped while its keys are empty. | Set test keys to check it. |

## Email, workflows and time

- **Mailpit** (http://localhost:8025) catches every email: invitations, magic links, invoices, reminders, review requests. Check the HTML and the plain-text part.
- **Temporal UI** (http://localhost:8233, namespace `tutortrack-local`):
  - Workflow IDs are `<process>:<organisation id>:<subject…>`. Find a run with a query such as `TutorTrackProcess="invoice-run"` or `OrganisationId="<uuid>"`.
  - Worker queues: `default`, `billing`, `payroll`, `comms`, `integrations`, `imports`, `privacy`.
  - Payloads are encrypted. To read them, set the UI's codec server to `http://localhost:8010/temporal-codec` (with credentials) while signed in as platform staff.
  - **The dev server cannot skip time.** To test timers: shorten the relevant tenant setting *before* the process starts (settings are read when a workflow starts); use the in-app "now" actions (Retry now, Recalculate now, Purge now, Issue statements); or trigger a Schedule from the UI's Schedules page. Long timers are covered by the backend replay tests (`temporal_env.skip`).
  - Don't signal or start workflows from the CLI: inputs must be encrypted.
  - The admin Settings page shows each record's process timeline (E32).
- **Celery beat** runs the periodic jobs (for example the 15-minute unconfirmed-lessons sweep and the nightly `extend_all_series_horizons`). Run the task in the shell to test it without waiting.

## Rate limits (defaults)

Sign-in 30/minute, 2FA 20/minute, magic link 10/hour, password reset 10/hour, signup 10/hour, email verification 30/hour, public forms 20/hour, public widget data 600/hour. Public API keys have their own limits with `X-RateLimit-*` headers (E27).

## Recording results

1. At the top of a run, note the **date, tester, environment** (host or compose; browser and device) and the **commit SHA** (`git rev-parse --short HEAD`).
2. Copy the files you will run into a run folder (for example `docs/test-plan/runs/2026-10-20/`), or fill the **Result** column on a branch.
3. Write one of:
   - **Pass**
   - **Fail** plus a link to the issue (say what you saw)
   - **Blocked** plus the reason (for example "needs real Xero sandbox")
   - **N/A** (not built, or not applicable to this release)
4. Add your initials and the date, for example `Pass — MB 2026-10-20`.
5. Add a line to the run log below.

### Run log

| Date | Tester | Commit | Environment | Files covered | Notes |
|---|---|---|---|---|---|
| | | | | | |

## Running the Playwright journeys

The automated journeys live in `frontend/e2e/`.

- `fixtures.ts` gives:
  - `pageAs(role)`: a browser page signed in as a seeded role.
  - `apiAs(role)`: a signed-in API client for arranging data.
  - `freshPageAs(role)`: a page with a new session, safe for sign-out tests.
  - Data helpers: `createFamily`, `createTutor`, `createJob`, `createLesson` and date helpers that use fixed London times.
- Sessions are cached per worker because sign-in is rate limited.
- Specs create their own data with unique names. So they run in any order and can be re-run on the same database.

**What the specs expect:**
- The API on :8010, seeded with `seed_demo`.
- The admin app on :5173 and the portal on :5174, both built and served with `vite preview`. The admin preview proxies `/api` to :8010 and `/portal` to :5174.
- Backend settings for e2e:
  - `CELERY_TASK_ALWAYS_EAGER=true`: domain events and tasks run in-process, so no Celery worker is needed.
  - `PLATFORM_REQUIRE_MFA=false`, so `platform@` can use the console without TOTP.
  - `THROTTLE_LOGIN=600/minute` and `THROTTLE_PUBLIC_FORM=1000/hour`, so parallel workers and retries never hit the rate limits.
- A reachable Temporal server. Workflows start, but no worker is needed for the assertions.
- The specs are listed in [traceability.md](traceability.md#playwright-specs).

**Local recipe for a small machine.** Use a separate database so your dev data stays intact.

1. `docker compose exec postgres psql -U tutortrack -d postgres -c "create database tutortrack_e2e owner tutortrack"`
2. Write a `.env` whose `DATABASE_URL`, `DATABASE_OWNER_URL` and `DATABASE_PLATFORM_URL` point at `tutortrack_e2e`, and set the four settings above. Optionally also give the run:
   - a separate Redis database;
   - its own S3 bucket name;
   - its own Temporal namespace: `docker compose exec temporal temporal operator namespace create --namespace tutortrack-e2e`, plus the five Keyword search attributes `OrganisationId`, `BranchId`, `SubjectType`, `SubjectId` and `TutorTrackProcess` (`temporal operator search-attribute create --namespace tutortrack-e2e --name <name> --type Keyword`).
3. Backend: `cd backend && uv run python manage.py ensure_db_roles && uv run python manage.py migrate && uv run python manage.py ensure_storage_bucket && uv run python manage.py seed_demo && uv run python manage.py runserver 127.0.0.1:8010 --noreload`
4. Build the apps: `pnpm --dir frontend --filter @tutortrack/admin build && pnpm --dir frontend --filter @tutortrack/portal build`
5. Serve them:
   - `pnpm --dir frontend --filter @tutortrack/portal preview --port 5174 --strictPort &`
   - `pnpm --dir frontend --filter @tutortrack/admin preview --port 5173 --strictPort &`
6. Install the browser once: `pnpm --dir frontend exec playwright install chromium`
7. Run the specs: `pnpm --dir frontend e2e --project=chromium --workers=1`
   - One spec: append its path, for example `e2e/billing.spec.ts`.
   - Watch the run: add `--ui` or `--headed`.

**Troubleshooting:**
- **WSL or minimal Linux.** If Chromium fails with missing `libnspr4`, `libnss3` or `libasound`, run `sudo pnpm --dir frontend exec playwright install-deps chromium`. Without sudo, download those packages with `apt-get download`, extract them with `dpkg -x`, and set `LD_LIBRARY_PATH` to the extracted `usr/lib/x86_64-linux-gnu`.
- Node may not resolve `*.localhost` names. `e2e/support/localhost-dns.ts`, loaded by `playwright.config.ts`, handles this.
- **Postgres "remaining connection slots are reserved".** `runserver` serves each request on a new thread, so persistent connections pile up. Development settings now default `DB_CONN_MAX_AGE` to 0; keep it at 0 for runserver.
- **Re-running on the same database.** Each run adds families, tutors and lessons. Some pickers list the first 200 records, so reset the e2e database (or restore a snapshot taken right after `seed_demo`) every few dozen runs.
- **Course dates.** The seeded term starts two weeks before `seed_demo` ran and lasts 12 weeks; re-seed a fresh database if it is older than that, or `courses.spec.ts` cannot schedule classes inside the term.

**CI and accessibility:**
- **CI.** The `e2e` job in `.github/workflows/ci.yml` does the same with docker compose, then runs the specs against the seeded stack. It starts Temporal, sets the settings above, and builds and serves both the admin app and the portal (CI uses the default `--workers` with two retries).
- **Accessibility.** `e2e/accessibility.spec.ts` scans key screens with `@axe-core/playwright` (see [accessibility.md](accessibility.md)).
