# E01 — Platform Foundations & Engineering Standards

| | |
|---|---|
| **Phase** | MVP (first) |
| **Depends on** | — |
| **Unlocks** | Everything |

## 1. Summary
Set up the monorepo, local dev environment, CI/CD, the Django and React skeletons, and the cross-cutting primitives every epic relies on: base models, money, timezone utilities, the domain event outbox, audit log, file storage, background jobs, API conventions, error handling, observability and test harness.

## 2. Goals
- A new developer (or Claude Code session) can run `make dev` and have a working stack in under 5 minutes.
- Every cross-cutting rule in `02-architecture.md` has a reusable implementation and tests.
- CI blocks merges that break lint, types, tests, migrations or the OpenAPI client.

## 3. Functional requirements

### FR-01-1 Monorepo and tooling
- Repo layout exactly as in `02-architecture.md §2`.
- `backend/pyproject.toml` managed by **uv**; `frontend` managed by **pnpm** workspaces.
- `Makefile` targets: `dev`, `down`, `test`, `test-be`, `test-fe`, `e2e`, `lint`, `fmt`, `typecheck`, `check`, `migrate`, `makemigrations`, `shell`, `seed`, `api-client`.
- pre-commit hooks: ruff, ruff-format, mypy (changed files), eslint, prettier, detect-secrets.
- **AC:** a fresh clone, `make dev`, then `make seed` gives a working admin login at `http://localhost:5173` with a demo organisation.

### FR-01-2 Docker local environment
- Services: `postgres:16`, `redis:7`, `backend` (Django runserver), `worker` (Celery), `beat`, `frontend` (Vite), `mailpit` (SMTP capture), `minio` (S3), `stripe-cli` (webhook forwarding, optional profile).
- Healthchecks on each service; `.env.example` documents every variable.

### FR-01-3 Django settings and configuration
- `config/settings/{base,dev,test,prod}.py`; env via `django-environ`.
- Security defaults in prod: `SECURE_*` headers, HSTS, secure cookies, `CSRF_TRUSTED_ORIGINS` from tenant domains (dynamic, via E24).
- `DEFAULT_AUTO_FIELD` unused: base model uses UUIDv7 PK.

### FR-01-4 Core base models (`core.models`)
- `TimeStampedModel` (created_at, updated_at).
- `UUIDModel` (UUIDv7 PK).
- `TenantModel(UUIDModel, TimeStampedModel)` with `organisation` FK, `created_by`, `updated_by`; managers `objects` (tenant-scoped via contextvar, **raises** `NoTenantContext` if none is set) and `all_tenants`.
- `BranchScopedModel(TenantModel)` adds `branch` FK and filters by `current_branch_ids` when the user is branch-restricted.
- `ArchivableModel` mixin: `archived_at`, `archive()`, `unarchive()`, `objects.active()`.
- **AC:** querying a `TenantModel` without a tenant context raises; querying inside `tenant_context(org_a)` never returns org B rows (tested).

### FR-01-5 Money and currency (`core.money`)
- `Money` immutable value object: `+ - * /` with Decimal, currency mismatch raises, `round_to_minor()`, `allocate(ratios)` (largest-remainder split for splitting payments or charges without losing pennies), `format(locale)`.
- Django model field `MoneyField` composite helper: generates `<name>_amount NUMERIC(14,2)` + `<name>_currency CHAR(3)`; `RateField` for 4dp rates.
- DRF serializer field: `{"amount": "12.50", "currency": "GBP"}` (amount as string).
- **AC:** Hypothesis tests prove `sum(allocate(m, ratios)) == m` for all inputs and that rounding is half-up at the minor unit, including 0-decimal (JPY) and 3-decimal (KWD) currencies.

### FR-01-6 Time utilities (`core.time`)
- Helpers: `now()`, `to_tz()`, `local_date_range_to_utc()`, `is_valid_timezone()`.
- RRULE helper wrapping `dateutil.rrule` that expands in a given IANA tz and handles DST (same wall-clock time).
- **AC:** a weekly 16:00 Europe/London series spanning the October DST change stays at 16:00 local.

### FR-01-7 Domain events and outbox (`core.events`)
- `DomainEvent` base dataclass (type, version, data, subject, actor), with a registry and JSON schema per event type.
- `publish(event)` writes an `OutboxEvent` row in the current transaction (`transaction.on_commit` is **not** used for persistence; the row is part of the txn).
- `outbox_dispatcher` Celery task: batches of 100, `SELECT … FOR UPDATE SKIP LOCKED`, dispatches to registered subscribers, records `ProcessedEvent(subscriber, event_id)` for idempotency, retries with backoff, and dead-letters after N attempts (visible in super-admin).
- Subscriber registration: `@subscribe("lesson.completed")` decorator in `handlers.py`, autodiscovered.
- **AC:** if the transaction rolls back, no event is dispatched. Each subscriber processes each event exactly once even when the dispatcher runs concurrently (tested with threads).

### FR-01-8 Audit log (`core.audit`)
- `AuditEntry` model (append-only; PG trigger blocks UPDATE/DELETE).
- `audit.record(obj, action, changes, actor)` called by services; a `ModelDiff` helper computes field diffs and redacts fields marked `sensitive`.
- Request context captures IP, UA, request_id and the impersonator.
- API: `GET /api/v1/audit?object_type=&object_id=` (permissioned).

### FR-01-9 Request context, logging and errors
- Middleware: request id (`X-Request-ID`), tenant resolution hook (implemented in E02), user and tz activation.
- `structlog` JSON logs with request id, org id and user id. PII scrubbing processor.
- DRF exception handler returning RFC 7807 Problem Details; domain exceptions (`BusinessRuleViolation`, `PermissionDenied`, `NotFound`, `Conflict`) map to 422/403/404/409.
- Sentry (backend and frontend) with tenant tags; OpenTelemetry tracing for Django, Celery, psycopg and Redis.

### FR-01-10 API framework
- DRF configured with cursor pagination, django-filter, ordering, `?fields=` sparse fieldsets, `?expand=`.
- `IdempotencyMiddleware` for POST with `Idempotency-Key` (stores response hash for 24h, keyed per org+user+key).
- ETag/If-Match support mixin for update views.
- drf-spectacular served at `/api/v1/schema/`, Swagger at `/api/v1/docs/`, ReDoc at `/api/v1/redoc/`.
- Health endpoints: `/healthz` (liveness), `/readyz` (DB, Redis, storage).

### FR-01-11 Background jobs
- Celery app with `TenantTask` base class (requires `organisation_id` kwarg, sets the tenant context and the RLS setting).
- Queues: `default`, `outbox`, `notifications`, `billing`, `integrations`, `imports`, `reports`.
- Beat schedule module; `fan_out_per_org(task)` helper.
- Celery tasks are idempotent; use `redis-lock` for singletons.

### FR-01-12 File storage
- `StoredFile` model (tenant, owner object generic FK, filename, content type, size, checksum, storage key, scan status, visibility).
- Presigned upload flow: `POST /api/v1/files/uploads` returns a URL; the client uploads; `POST …/complete`; AV scan task (ClamAV container); download via short-lived presigned URL after a permission check.
- Size and type allow-lists configurable per org.

### FR-01-13 Sequence numbers
- `core.sequences.next_number(org, key, prefix, padding)`, gap-free, row-locked, used for invoice, credit note, pay run, job and enquiry references.

### FR-01-14 Feature flags
- `django-waffle` or a custom `FeatureFlag` model with global, per-plan and per-org overrides; `@requires_feature("courses")` decorator and a frontend hook `useFeature()`. Used heavily by E04 entitlements.

### FR-01-15 Frontend skeleton
- `apps/admin`, `apps/portal`, `apps/widgets`, `packages/ui`, `packages/api-client`, `packages/i18n`.
- Auth bootstrap (session + CSRF), routing, layout shell, toast/error boundary, TanStack Query defaults, form primitives, data grid component (TanStack Table) with server-side pagination, filters and saved views.
- Storybook for `packages/ui`.
- Theme tokens via CSS variables, overridable by tenant branding.

### FR-01-16 CI/CD
- GitHub Actions: `backend` (ruff, mypy, pytest with PG/Redis services, migrations check, coverage), `frontend` (eslint, tsc, vitest, build), `contract` (regenerate OpenAPI and TS client, fail on diff), `e2e` (Playwright against docker-compose; nightly + on main).
- Build and push images; deploy to staging on main; production via manual approval and tag.
- Infra-as-code baseline in `infra/terraform` (VPC, RDS, ElastiCache, ECS, S3, CloudFront, Secrets Manager).

### FR-01-17 Seed and demo data
- `make seed` creates: a platform super-admin, a "Bright Minds Tutoring" demo org with 2 branches, 5 tutors, 20 clients, 30 students, services, 3 months of lessons, invoices and payments. Factories double as the seeding source.

## 4. Data model
`OutboxEvent(id, organisation_id, type, version, payload JSONB, occurred_at, available_at, attempts, last_error, dispatched_at)`
`ProcessedEvent(subscriber, event_id, processed_at)` (unique subscriber+event_id)
`AuditEntry(id, organisation_id, actor_user_id, impersonator_user_id, action, object_type, object_id, object_repr, changes JSONB, ip, user_agent, request_id, created_at)`
`StoredFile(...)`, `Sequence(organisation_id, key, next_value)`, `IdempotencyRecord(org, user, key, request_hash, response_status, response_body, expires_at)`, `FeatureFlag`, `FeatureFlagOverride`.

## 5. Non-functional
- Outbox dispatch latency p95 < 5s.
- Test suite parallelised (`pytest-xdist`); CI under 10 minutes.

## 6. Delivery plan
- [ ] **E01-T01** Monorepo scaffold, uv/pnpm, Makefile, pre-commit, docker-compose with all services, `.env.example`.
- [ ] **E01-T02** Django project, settings split, structlog, Sentry, health endpoints, RFC 7807 handler.
- [ ] **E01-T03** Core base models (UUIDv7, TimeStamped, Archivable) and the tenant context primitives (contextvar + manager raising without context). Full tenancy arrives in E02.
- [ ] **E01-T04** Money value object, fields and serializer, with Hypothesis tests.
- [ ] **E01-T05** Time and recurrence utilities with DST tests.
- [ ] **E01-T06** Outbox: models, publish, dispatcher, subscriber registry, idempotency, dead-letter.
- [ ] **E01-T07** Audit log with append-only trigger, diff helper and API.
- [ ] **E01-T08** DRF config: pagination, filters, sparse fields, expand, idempotency middleware, ETag mixin, OpenAPI docs.
- [ ] **E01-T09** Celery with TenantTask, queues, beat module, fan-out helper.
- [ ] **E01-T10** File storage with presigned uploads, AV scan and permission-checked downloads.
- [ ] **E01-T11** Sequence numbers and feature flags.
- [ ] **E01-T12** Frontend workspace: admin/portal/widgets apps, ui package, generated api-client, auth bootstrap, data-grid component, Storybook.
- [ ] **E01-T13** CI pipelines (backend, frontend, contract, e2e) and Terraform baseline.
- [ ] **E01-T14** Seed/demo data command.
