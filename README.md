# TutorTrack

Multi-tenant SaaS to run a tutoring business end to end: people and CRM, scheduling, lesson
delivery, billing, payments, payroll, communications, automations, portals for clients, students
and tutors, websites, reporting, a public API and an AI assistant. Python (Django) and
PostgreSQL backend, React and TypeScript frontends.

**Status:** all 32 epics (E01–E32) are built, plus every gap batch (G1–G6). The items that
need real provider credentials or infrastructure are listed at the end of
[docs/05-gap-backlog.md](docs/05-gap-backlog.md). E33 (the workflow designer) is in
progress: the sequence engine and its catalogue are done. Build order and progress:
[docs/04-roadmap.md](docs/04-roadmap.md).

## Guides

| Guide | For |
|---|---|
| [User guide](docs/guides/user-guide.html) | Office staff, tutors, clients, students and affiliates using TutorTrack day to day |
| [Admin guide](docs/guides/admin-guide.html) | Organisation admins who set TutorTrack up, and operators who run the platform |
| [API guide](docs/guides/api-guide.html) | Developers integrating through the REST API, OAuth apps and webhooks |

The guides are static HTML: open them in a browser straight from the repo, or in the running
admin app at `/guides/` (the Help panel links to the section about each page). How they are
kept current: [docs/guides/README.md](docs/guides/README.md).

## Quick start (Linux / macOS / WSL)

Prerequisites: Docker, Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22, pnpm 9, make.
On a fresh Ubuntu machine `bash scripts/setup-ubuntu.sh` installs them and runs the steps below.

```bash
cp .env.example .env
make infra                     # postgres, redis, s3 (SeaweedFS), mailpit, temporal
make install                   # uv sync + pnpm install
make migrate                   # creates the database roles, then migrates
cd backend && uv run python manage.py ensure_storage_bucket && cd ..
make seed                      # admin@tutortrack.localhost / org "brightminds"
```

Then run each of these in its own terminal:

```bash
cd backend && uv run python manage.py runserver 127.0.0.1:8010         # API
cd backend && uv run celery -A config worker -l INFO                    # background jobs, all queues (-P solo on Windows)
cd backend && uv run celery -A config beat -l INFO                      # timed jobs: reminders, checks, retries
cd backend && uv run python manage.py temporal_worker --task-queue all  # workflows
pnpm --dir frontend dev                                                 # admin app
pnpm --dir frontend/apps/portal dev                                     # client and tutor portal
```

Or run the whole stack in Docker with `make dev`.

| What | Where |
|---|---|
| Admin app | http://brightminds.localhost:5173 (the subdomain selects the organisation) |
| Client, student and tutor portal | http://brightminds.localhost:5174/portal/ |
| Embeddable widgets (dev server) | http://localhost:5175 |
| API and interactive docs | http://localhost:8010/api/v1/docs/ |
| Platform console | http://localhost:5173/platform (platform admins only) |
| Mailpit (outgoing email) | http://localhost:8025 |
| Temporal UI | http://localhost:8233 |
| S3 (SeaweedFS) | http://localhost:9010 |

Sign in as `admin@tutortrack.localhost` with the password in `SEED_ADMIN_PASSWORD`
(default `tutortrack`).

## Repository layout

```
backend/              Django project: config/ (settings, Celery, URLs) and tutortrack/<app>/
frontend/apps/admin   Admin app and platform console (React, Vite, TanStack)
frontend/apps/portal  Client, student, tutor and affiliate portal (PWA, offline, push)
frontend/apps/widgets Embeddable website widgets
frontend/apps/mobile  Capacitor native shells for the portal (built by its own workflow)
frontend/packages     api-client (generated from OpenAPI), i18n, ui (shadcn components)
frontend/e2e          Playwright end-to-end journeys
infra/                Terraform (AWS) and local infrastructure config
docs/                 Product spec, architecture, epics, ADRs, runbooks, compliance, test plan, guides
```

### Backend apps

Each app in `backend/tutortrack/` owns its models, `services.py` (writes), `selectors.py`
(reads), API, permissions, events and Temporal workflows.

| App | Responsibility | Epic |
|---|---|---|
| `core` | Tenant models and RLS, events and outbox, audit, money, crypto, permissions, API conventions | E01, E02 |
| `tenancy` | Organisations, branches, org settings, onboarding, sole-trader (solo) mode | E02 |
| `identity` | Users, sign-in, MFA, passkeys, SSO, roles and custom roles, invitations | E03 |
| `workflows` | Temporal runtime, tenant-aware workflows and activities | E32 |
| `subscriptions` | SaaS plans, trials, entitlements, Stripe Billing | E04 |
| `people` | Clients, contacts, students, tutors, households, duplicates and merge | E05 |
| `crm` | Notes, tasks, tags, custom fields, search | E05 |
| `catalogue` | Services, subjects, rates, tax rates, pay tiers, pricing rules, rooms | E06 |
| `jobs` | Jobs and tutor assignment | E07 |
| `scheduling` | Lessons, recurrence, calendar, availability, self-booking | E08 |
| `delivery` | Attendance, lesson reports, lesson feedback, cancellation policies | E09 |
| `billing` | Ledger, invoices, credit notes, packages, late fees, payment requests | E10 |
| `payments` | Stripe, GoCardless, PayPal, auto-pay, refunds, reconciliation | E11 |
| `payroll` | Pay items, pay runs, expenses, payouts, tax forms | E12 |
| `comms` | Email, SMS and push, templates, inbox, broadcasts, notification preferences | E13 |
| `automations` | Trigger/condition/action automations and workflow sequences on Temporal: plain questions, timed waits, Stop when, pause | E14, E33 |
| `portal` | Client, student and tutor portal APIs | E15, E16 |
| `leads` | Enquiries, pipeline, forms (with file uploads), waitlist with tutor-capacity suggestions, proposals | E17 |
| `recruitment` | Job openings, tutor applications (CV and video uploads), interview booking, onboarding, compliance checks, probation reviews, offboarding, subject tests | E18 |
| `matching` | Tutor matching (incl. exam boards, SEN experience, optional gender preference) and the job marketplace | E19 |
| `courses` | Group classes, courses, terms and enrolment | E20 |
| `learning` | Homework, resources (also in the online classroom), progress reports (manual or on a schedule) and assessments | E21 |
| `integrations` | Integration framework and provider connections | E22 |
| `calendar_sync` | Calendar sync and online lesson (video) integrations | E22 |
| `accounting` | Xero, QuickBooks, Sage and FreeAgent sync (per-branch ledgers, payment read-back) | E23 |
| `sites` | Public website builder, widgets, custom domains, white-labelling | E24 |
| `growth` | Reviews, referrals and affiliates | E25 |
| `reporting` | Reports (incl. referral, affiliate, review and room utilisation), dashboards, custom and scheduled reports, warehouse export | E26 |
| `developer` | Public API surface, API keys, OAuth apps, webhooks, sandboxes | E27 |
| `migration` | Data import, export and competitor migration | E28 |
| `privacy` | Consent, data subject requests, erasure, retention, safeguarding | E29 |
| `platform_admin` | Platform console: tenants, flags, support access, operations | E30 |
| `success` | Customer success: tenant health, product analytics, support inbox | E30 |
| `ai` | AI assistant: drafts, suggestions, copilot (Claude) | E31 |

## Development

| Command | Does |
|---|---|
| `make check` | Everything CI runs: lint, types, migrations check, tests, API client drift, guides check. **Must pass before a ticket is done.** |
| `make test` | Backend (pytest, parallel) and frontend (vitest) tests |
| `make e2e` | Playwright journeys (needs `make dev`) |
| `make api-client` | Regenerate the OpenAPI schema and TypeScript client |
| `make docs` | Regenerate the API guide reference from OpenAPI and the webhook catalogue |
| `make docs-check` | Fail if the guides or this README are out of date |
| `make help` | List every target |

Small machine? `make check PYTEST_WORKERS=2 FE_CONCURRENCY=1`.

Engineering rules for every change (tenancy, services and selectors, events, audit, money,
time, permissions, API conventions, tests, i18n, accessibility) are in [CLAUDE.md](CLAUDE.md).

## Documentation

- [docs/README.md](docs/README.md): product and engineering specification index
- [docs/02-architecture.md](docs/02-architecture.md) and [docs/03-domain-model.md](docs/03-domain-model.md): read before any change
- [docs/epics/](docs/epics/): one file per epic with requirements, delivery plan and implementation notes
- [docs/adr/](docs/adr/): architecture decision records
- [docs/runbooks/](docs/runbooks/): deploy, rollback, restore, incidents, alerts
- [docs/compliance/](docs/compliance/) and [docs/security/](docs/security/): policies and the ASVS checklist
- [docs/test-plan/](docs/test-plan/): manual test cases, journeys and traceability

## Keeping this README and the guides current

Any change that adds, removes or renames a backend app, a screen, a setting, an API endpoint
or a webhook event updates this README and the matching guide in the same pull request.
`make docs-check` (in `make check` and CI) enforces the parts that can be checked mechanically;
see [docs/guides/README.md](docs/guides/README.md).
