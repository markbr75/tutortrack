# 02 — Architecture

This document defines the technical foundation that **every epic must follow**. Where an epic is silent, this document applies.

## 1. Technology stack

| Layer | Choice | Rationale |
|---|---|---|
| Language | **Python 3.12+** | Requirement |
| Web framework | **Django 5.x** | Mature ORM, migrations, admin, auth and i18n; ideal for a CRUD-heavy, multi-module SaaS |
| API | **Django REST Framework** + **drf-spectacular** (OpenAPI 3.1) | Powerful permissions, filtering, throttling and pagination; generated docs; one API for internal and public use |
| Database | **PostgreSQL 16+** | Requirement. Uses JSONB, row-level security, exclusion constraints (no double-booking), `tstzrange`, full-text search, partial indexes |
| Async jobs | **Celery 5** + **Redis** (broker) and **Celery Beat** (global crons) | Short, stateless tasks: outbox dispatch, message sends, scans, webhook deliveries |
| Durable workflows | **Temporal** (Python SDK `temporalio`; Temporal Cloud in production, CLI dev server locally) | Long-running, multi-step processes with timers, retries and human approvals: invoice runs, dunning, pay runs, offers, compliance expiry, automations, imports, DSARs (E32, ADR 0002) |
| Cache / locks | Redis | Caching, rate limiting, distributed locks (`django-redis`, `redis-lock`) |
| Frontend (admin, tutor, client apps) | **React 18 + TypeScript + Vite**, TanStack Query, TanStack Router, Tailwind CSS, shadcn/ui, FullCalendar (premium for resource views), React Hook Form + Zod | Rich interactive calendar and data grids; installable PWA |
| API client | TypeScript client **generated from OpenAPI** (`openapi-typescript` + `openapi-fetch`) | Keeps the frontend in lockstep with the backend |
| Public widgets | Web Components (Lit) served from CDN | Embeddable on any site (Wix, WordPress, Squarespace) |
| Search | Postgres full-text search (`SearchVector`, trigram). Optional later: OpenSearch | Keep infrastructure small |
| File storage | S3-compatible object storage (`django-storages`, boto3); presigned PUT uploads; AV scanning (ClamAV). Local dev uses SeaweedFS | Documents, resources, avatars |
| Email | Provider abstraction; default **Postmark** (transactional) and **SES** (broadcast). Inbound parse for reply-to-thread | Deliverability, bounce handling |
| SMS / WhatsApp | **Twilio** (abstraction allows MessageBird/Vonage) | Global coverage |
| Push | Web Push (VAPID) for the PWA; FCM/APNs later for native shells | E16 |
| Payments | **Stripe** (Connect, Billing for our own SaaS), **GoCardless**, **PayPal** | E04, E11 |
| PDF | WeasyPrint (HTML→PDF templates) | Invoices, statements, reports |
| Observability | Sentry, OpenTelemetry traces, structured JSON logs (`structlog`), Prometheus metrics | |
| Infra | Docker; deploy to AWS (ECS Fargate + RDS Postgres + ElastiCache + S3 + CloudFront) via Terraform. Local: docker-compose | Cloud-agnostic containers |
| CI/CD | GitHub Actions: lint, type-check, tests, migrations check, build, deploy | |
| Quality | `ruff` (lint+format), `mypy` (strict on domain/services), `pytest`, `pytest-django`, `factory_boy`, `hypothesis` for money/recurrence, Playwright E2E, `eslint`, `vitest` | |

Alternatives considered: FastAPI (rejected: we would rebuild admin, auth, migrations and permissions); HTMX (rejected for staff apps because the calendar and grids need a rich client; acceptable for super-admin pages).

## 2. Repository layout (monorepo)

```
/
├── CLAUDE.md
├── Makefile                  # make dev, make test, make check, make migrate, make api-client
├── docker-compose.yml
├── backend/
│   ├── pyproject.toml
│   ├── config/               # settings (base/dev/test/prod), urls, celery, asgi/wsgi
│   ├── tutortrack/
│   │   ├── core/             # base models, tenancy, money, audit, events/outbox, utils
│   │   ├── tenancy/          # Organisation, Branch, domains, settings      (E02)
│   │   ├── identity/         # User, Membership, Roles, auth, SSO, 2FA      (E03)
│   │   ├── subscriptions/    # our SaaS plans/billing/entitlements          (E04)
│   │   ├── people/           # Clients, Contacts, Students, Tutors, CRM     (E05)
│   │   ├── catalogue/        # Subjects, levels, services, rates, packages  (E06)
│   │   ├── jobs/             # Jobs, assignments                            (E07)
│   │   ├── scheduling/       # Lessons, recurrence, availability, rooms     (E08)
│   │   ├── delivery/         # Attendance, cancellations, lesson reports    (E09)
│   │   ├── billing/          # Client ledger, invoices, credit, packages    (E10)
│   │   ├── payments/         # Providers, payment methods, transactions     (E11)
│   │   ├── payroll/          # Tutor pay items, pay runs, payouts, expenses (E12)
│   │   ├── comms/            # Templates, messages, notifications           (E13)
│   │   ├── automation/       # Rules engine                                 (E14)
│   │   ├── leads/            # Enquiries, pipeline                          (E17)
│   │   ├── recruitment/      # Applications, compliance                     (E18)
│   │   ├── matching/         # Matching, job board                          (E19)
│   │   ├── courses/          # Classes, courses, terms, enrolment           (E20)
│   │   ├── learning/         # Homework, resources, progress                (E21)
│   │   ├── integrations/     # Calendar, video, accounting connectors       (E22, E23)
│   │   ├── sites/            # Website, widgets, branding                   (E24)
│   │   ├── growth/           # Reviews, referrals, affiliates               (E25)
│   │   ├── reporting/        # Reports, dashboards, exports                 (E26)
│   │   ├── developer/        # API keys, OAuth apps, webhooks               (E27)
│   │   ├── migration/        # Importers                                    (E28)
│   │   ├── privacy/          # GDPR, retention, safeguarding                (E29)
│   │   ├── platform_admin/   # Super-admin, support tools                   (E30)
│   │   └── ai/               # AI features                                  (E31)
│   └── tests/
├── frontend/
│   ├── apps/admin/           # staff/owner app
│   ├── apps/portal/          # client, student, tutor and affiliate portals (one app, role-based shells)
│   ├── apps/widgets/         # embeddable web components
│   └── packages/{ui,api-client,i18n}
├── infra/terraform/
└── docs/
```

### Django app internal structure (each domain app)

```
<app>/
  models.py        # persistence only; no business logic beyond invariants
  services.py      # write operations (commands). All mutations go through services
  selectors.py     # read/query functions
  events.py        # domain event dataclasses emitted by this app
  handlers.py      # subscribers to other apps' events
  api/             # DRF serializers, viewsets, urls (versioned: /api/v1/)
  tasks.py         # Celery tasks (thin; call services)
  permissions.py   # permission codenames and checks
  admin.py         # Django admin (platform operators only)
  tests/
```

**Rule:** Views and serializers never contain business logic; they call `services.*`. Apps communicate through **services and domain events**, never by writing directly to another app's tables.

## 3. Multi-tenancy

- **Model:** shared database, shared schema, `organisation_id` on every tenant-owned row. Optional `branch_id` where data is branch-scoped.
- **Base class:** `TenantModel(models.Model)` with `organisation = FK(Organisation)`, a default manager `TenantManager` that **automatically filters by the current tenant** from a context variable, and `all_tenants` as an explicit unscoped manager (super-admin only).
- **Request context:** middleware resolves the tenant from (1) the custom domain or subdomain (`acme.tutortrack.app`), or (2) the `X-Organisation` header for API tokens scoped to an org. It sets `contextvars` `current_organisation` and `current_branch_ids` (the branches the user may see).
- **Defence in depth:** PostgreSQL **Row-Level Security** policies on tenant tables using `current_setting('app.current_org')::uuid`, set per transaction by middleware and by a Celery task base class. Migrations add RLS policies via a helper.
- **Celery:** every task takes `organisation_id` explicitly and runs inside `tenant_context(org_id)`.
- **Uniqueness:** unique constraints include `organisation_id` (e.g. invoice number unique per org).
- **Tests:** a mandatory test fixture creates two tenants and asserts no cross-tenant leakage for every list/detail endpoint (shared test mixin `TenantIsolationTestMixin`).

## 4. Identifiers, time and money

- **Primary keys:** UUIDv7 (`uuid6` package or PG `uuidv7()` when available). Sorted by time, safe to expose.
- **Human references:** per-tenant sequential numbers for invoices (`INV-000123`), credit notes, pay runs and jobs, generated by a gap-free per-org sequence table locked with `SELECT … FOR UPDATE`.
- **Time:** store all timestamps as `timestamptz` (UTC). Each Organisation, Branch, User, Location and Lesson carries an IANA `timezone`. Display in the viewer's timezone, with the lesson timezone shown when different. Recurrence is expanded in the **lesson's local timezone** so DST changes keep lessons at the same wall-clock time.
- **Money:** a `Money` value object (`amount: Decimal`, `currency: str`) `MoneyField` stores `<name>_amount NUMERIC(14,2)` (`RateField`: `NUMERIC(14,4)`) and reads the currency from an explicit `CurrencyField` on the same model (usually one shared `currency` column per record). Use the `decimal` module only; rounding is `ROUND_HALF_UP` to the currency's minor unit, at **line level**. Floats are never used for money. Currency minor units come from ISO 4217 data (`babel`).
- **Tax:** each line stores `tax_rate_id`, `tax_amount`, `net`, `gross`. Prices can be tax-inclusive or tax-exclusive per organisation.

## 5. Domain events and the transactional outbox

- Services emit domain events (e.g. `lesson.completed`, `invoice.issued`, `payment.succeeded`) by calling `events.publish(event)` **inside the DB transaction**. This writes to the `outbox_event` table.
- A Celery worker (`outbox_dispatcher`) reads unprocessed rows (`FOR UPDATE SKIP LOCKED`) and dispatches each to:
  1. in-process **handlers** registered by apps (e.g. billing listens to `lesson.completed`)
  2. the **notification** system (E13)
  3. the **automation engine** (E14)
  4. **webhook** deliveries (E27)
  5. **integration** syncs (E22/E23)
- Event envelope: `{id, type, version, occurred_at, organisation_id, branch_id, actor: {type, id}, subject: {type, id}, data: {...}, changes: {...}}`.
- Handlers must be **idempotent** (keyed on event id).
- A canonical event catalogue lives in `docs/03-domain-model.md §5` and is extended by each epic.

## 6. Audit log

- Every service mutation writes an `AuditEntry` (actor, impersonator if any, org, object type and id, action, field-level diff, IP, user agent, request id). It is append-only (enforced by a DB trigger that blocks UPDATE/DELETE).
- Visible on each record's "History" tab and in a global audit search (E29).

## 7. Permissions model (summary; detail in E03)

- **RBAC + scopes.** Permission codenames like `billing.invoice.issue`. Roles are bundles of permissions. Built-in roles (Owner, Admin, Branch Manager, Coordinator, Finance, Tutor, Client, Student, Affiliate) can be cloned into custom roles.
- **Data scopes:** All, Branch (assigned branches), Own (records linked to the user, e.g. a tutor's own students and lessons).
- **Field-level visibility:** sensitive fields (charge rate vs pay rate, safeguarding notes, DOB) are guarded by permissions, and serializers drop fields the viewer cannot see.
- Checks are enforced in the API layer (DRF permission classes) **and** in selectors (queryset scoping).

## 8. API conventions

- Base path `/api/v1/`. JSON. `snake_case` fields. ISO 8601 datetimes with offset.
- Cursor pagination (`?cursor=`), `?page_size` ≤ 200.
- Filtering via `django-filter`; ordering via `?ordering=`; sparse fields `?fields=`; expansion `?expand=client,students`.
- Errors: RFC 7807 Problem Details `{type, title, status, detail, errors: {field: [..]}}`.
- Idempotency: all POSTs that create financial objects accept an `Idempotency-Key` header, stored for 24h.
- Concurrency: `ETag`/`If-Match` on updates of key resources (lesson, invoice, job) to prevent lost updates.
- Auth: session cookie + CSRF for first-party apps; Bearer tokens (API keys / OAuth2 access tokens) for third parties.
- Rate limits per token and per IP (Redis).
- Every endpoint documented in OpenAPI with examples, and the TS client is regenerated in CI (fails on drift).

## 9. Background work: Celery vs Temporal

**Rule (E32 §2):** use **Temporal** when a process has multiple steps that must all happen, waits on timers longer than a few minutes, waits for a human or an external callback, must be visible as a timeline, or must be cancellable mid-flight. Use **Celery** for single, short, stateless tasks. If you would add a `next_*_at` column and a sweeper, use a workflow instead.

- Temporal workflows are deterministic; side effects happen in activities that call services inside `tenant_context`. Workflow IDs are tenant-prefixed (`invoice-dunning:{org}:{invoice}`) for idempotent starts.
- Domain events reach workflows through the outbox → Temporal bridge (start/signal). Human decisions arrive as signals from API endpoints.
- Per-tenant recurring processes (invoice runs, pay-run cut-offs, retention purges) use **Temporal Schedules**; global housekeeping crons stay on Celery Beat.
- Workflow payloads are encrypted with a KMS-backed codec; payloads carry IDs, not documents.

### Writing a workflow (pattern; reference: `tutortrack/workflows/demo.py`)

```python
# <app>/activities.py (or alongside the workflow) - side effects, idempotent
@dataclass(frozen=True, kw_only=True)
class DunningInput(WorkflowInput):          # first field: organisation_id (from WorkflowInput)
    invoice_id: str

@tenant_activity                            # runs in tenant_context, actor = the workflow
def send_reminder(input: DunningInput) -> None:
    with transaction.atomic():
        services.send_reminder(input.invoice_id)
        publish(ReminderSent(...), dedupe_key=idempotency_key())   # once per activity

# <app>/workflows.py - deterministic orchestration only (no ORM/network/clock)
@register_workflow(process="invoice-dunning", task_queue="billing",
                   cancel_permission="billing.invoice.manage")
@workflow.defn
class InvoiceDunningWorkflow:
    @workflow.signal
    def paid(self) -> None: self.done = True
    @workflow.query
    def state(self) -> dict[str, str]: return {"step": self.step}
    @workflow.run
    async def run(self, input: DunningInput) -> str:
        settings = await workflow.execute_activity(snapshot_settings, ...)  # snapshot once
        await report_step(input, "waiting")                                # process timeline
        if await wait_until_local(due, calendar, until=lambda: self.done): ...
        await workflow.execute_activity(send_reminder, input, start_to_close_timeout=...)

# <app>/handlers.py - start/signal from domain events (idempotent by workflow id)
bridge.on("invoice.issued", start=InvoiceDunningWorkflow,
          id=lambda e: workflow_id("invoice-dunning", e.organisation_id, e.subject["id"]),
          input=lambda e: DunningInput(organisation_id=str(e.organisation_id),
                                       invoice_id=e.subject["id"]))
bridge.on("payment.succeeded", signal="paid",
          id=lambda e: workflow_id("invoice-dunning", e.organisation_id, e.data["invoice_id"]))
```

- From services use `core.workflows.start()` / `signal()` (after commit); human decisions are
  API endpoints that call `signal()`.
- Per-tenant recurring processes: `core.workflows.schedules.ensure_schedule(...)`; they pause
  with the organisation on suspension and are deleted on closure.
- Tests: the `temporal_env` fixture (time-skipping; `env.result(id)` skips timers),
  `temporal_local_env` for Schedules; workflow tests that run activities use
  `django_db(transaction=True)`. Ship a happy-path, signal, timer, retry and **replay** test
  (record histories into `backend/tests/workflow_histories/`, see its README). Breaking a
  replay means `workflow.patched()` or Worker Versioning, never re-recording.
- Locally `make infra` starts the Temporal dev server (UI on http://localhost:8233); run
  workers with `manage.py temporal_worker --task-queue all`.

### Celery Beat (global crons)

Centralised in `config/celery_schedule.py`. Jobs must be **idempotent and tenant-sharded**: a master task fans out one task per active organisation. Examples: reminder dispatch (every 5 min), auto-invoice generation (hourly, per org's configured schedule), dunning (daily), calendar sync (every 5 min, plus push channels), compliance expiry checks (daily), payout runs (per schedule), outbox dispatch (continuous), webhook retries (exponential backoff).

## 10. Frontend architecture

- **Admin app** (`apps/admin`): role-aware navigation; global search (⌘K); data grids with saved views, column chooser, bulk actions and CSV export; calendar with resource (tutor/room) views; record pages with tabs (Overview, Lessons, Billing, Notes, Documents, History).
- **Portal app** (`apps/portal`): one installable **PWA** with role shells (Client, Student, Tutor, Affiliate); offline cache of upcoming schedule; push notifications; tenant branding at runtime from `/api/v1/branding`.
- **Design system** in `packages/ui` (shadcn/ui + Tailwind tokens; tenant theme via CSS variables).
- **i18n:** all strings via `i18next`; backend via Django gettext. Locale formatting for dates and currencies. Launch languages: en-GB, en-US; ready for fr, es, de, nl, pl.
- **Accessibility:** WCAG 2.2 AA. Keyboard navigable calendar, focus management, colour-contrast tokens.

## 11. Environments and deployment

- `local` (docker-compose: postgres, redis, mailpit, minio, stripe-cli), `ci`, `staging`, `production`.
- 12-factor config via env vars (`django-environ`); secrets in AWS Secrets Manager.
- Zero-downtime deploys; migrations must be backward compatible (expand/contract pattern).
- Data residency: deploy stacks per region (UK/EU, US, AU) later. The Organisation has a `region` field from day one.
- Backups: RDS PITR (35 days) plus daily logical dumps to a separate account. Restore drill quarterly.

## 12. Non-functional requirements (global)

| Area | Target |
|---|---|
| Availability | 99.9% monthly (core app and API) |
| Performance | p95 < 300ms for reads, < 800ms for writes; calendar week view with 500 lessons < 1s |
| Scale | 10k tenants, 50k tutors, 5M lessons/year on a single primary DB with read replica |
| Security | OWASP ASVS L2; encryption at rest (RDS/S3 KMS) and in transit (TLS 1.2+); field-level encryption for secrets and tokens and highly sensitive PII (e.g. safeguarding notes, bank details) via `cryptography` Fernet with KMS-managed keys |
| Privacy | GDPR/UK-GDPR, COPPA-aware, CCPA; DPA available to tenants |
| Accessibility | WCAG 2.2 AA |
| Testing | ≥ 85% line coverage on `services`/`selectors`; every FR has at least one automated test |
