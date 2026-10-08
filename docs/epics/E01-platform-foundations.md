# E01 — Platform Foundations & Engineering Standards

| | |
|---|---|
| **Phase** | MVP (first) |
| **Status** | ✅ Done (2026-10-08) |
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
- [x] **E01-T01** Monorepo scaffold, uv/pnpm, Makefile, pre-commit, docker-compose with all services, `.env.example`.
- [x] **E01-T02** Django project, settings split, structlog, Sentry, health endpoints, RFC 7807 handler.
- [x] **E01-T03** Core base models (UUIDv7, TimeStamped, Archivable) and the tenant context primitives (contextvar + manager raising without context). Full tenancy arrives in E02.
- [x] **E01-T04** Money value object, fields and serializer, with Hypothesis tests.
- [x] **E01-T05** Time and recurrence utilities with DST tests.
- [x] **E01-T06** Outbox: models, publish, dispatcher, subscriber registry, idempotency, dead-letter.
- [x] **E01-T07** Audit log with append-only trigger, diff helper and API.
- [x] **E01-T08** DRF config: pagination, filters, sparse fields, expand, idempotency middleware, ETag mixin, OpenAPI docs.
- [x] **E01-T09** Celery with TenantTask, queues, beat module, fan-out helper.
- [x] **E01-T10** File storage with presigned uploads, AV scan and permission-checked downloads.
- [x] **E01-T11** Sequence numbers and feature flags.
- [x] **E01-T12** Frontend workspace: admin/portal/widgets apps, ui package, generated api-client, auth bootstrap, data-grid component, Storybook.
- [x] **E01-T13** CI pipelines (backend, frontend, contract, e2e) and Terraform baseline.
- [x] **E01-T14** Seed/demo data command.

## 7. Implementation notes (as built, 2026-10-08)

Where the build differs from, or adds to, the requirements above. Later epics should treat
these as the source of truth.

| Area | As built | Why |
|---|---|---|
| Local S3 | **SeaweedFS** (`chrislusf/seaweedfs`) instead of MinIO; bucket created by `manage.py ensure_storage_bucket` | MinIO no longer publishes container images |
| Host ports | Postgres **5442**, Redis **6389**, API **8010**, S3 **9010** | Avoid clashes with other local services |
| Money fields (FR-01-5) | `MoneyField(currency_field="currency")` stores `<name>_amount` and reads the currency from an **explicit** `CurrencyField` on the model (shared by all amounts on a record). `instance.total` returns `Money`; `instance.total_amount` returns `Decimal`. Saving more decimals than the column allows raises instead of silently rounding | Auto-generated currency columns break Django migrations; one currency per document is the common case |
| Org and User models | Minimal `tenancy.Organisation` and `identity.User` (email login, UUIDv7) created in E01 | `TenantModel` needs the Organisation FK and Django needs `AUTH_USER_MODEL` from the first migration. **E02/E03 extend these models; do not recreate them** |
| Branch scoping (FR-01-4) | `BranchScopedModel` deferred to **E02-T04** | Needs the Branch model |
| Tenant resolution | Subdomain resolver only (`<slug>.<TENANT_BASE_DOMAIN>`), pluggable via `settings.TENANT_RESOLVER` | Header resolution needs the E03 membership check; custom domains are E24 |
| Postgres RLS | Not yet enabled; the tenant-scoped manager plus `TenantIsolationTestMixin` provide isolation for now | Lands in **E02-T03** with the non-owner app DB role |
| Permissions | `core.permissions.has_perm()` / `HasPermission.for_("x.y")` hook: superuser or Django perms until E03 | E03 swaps in RBAC without touching call sites |
| Audit (FR-01-7) | Postgres trigger blocks UPDATE/DELETE unless `SET LOCAL tutortrack.audit_purge='on'`. TRUNCATE is not trigger-blocked (Django test flush needs it); E02 table ownership prevents it | |
| Idempotency (FR-01-10) | Keyed by organisation + principal (user id, or SHA-256 of the `Authorization` header for token clients) + key; 5xx and >1 MB responses are not stored | Middleware runs before DRF token auth |
| Files (FR-01-12) | Presigned **PUT** (not POST); `complete` verifies size and type with HEAD; scan status `skipped` when `CLAMAV_ENABLED=false` (local only); infected files are deleted and the record rejected | Simpler; works with S3 and SeaweedFS |
| Sequences (FR-01-13) | `core.sequences.next_number(key, prefix=, padding=)` must run inside the document's transaction (raises otherwise) | Guarantees gap-free numbering |
| Seed data (FR-01-17) | Registry: each app adds `seeds.py` with `@seed_step(order=N)`. E01 seeds the platform admin, **Bright Minds Tutoring** (`brightminds`) and baseline flags; clients, tutors and lessons arrive with their epics | Avoids a monolithic seed script |
| Frontend dev | Apps served at `http://<slug>.localhost:5173`; Vite proxies `/api` and `/django-admin` keeping the Host header, so tenancy, cookies and CSRF behave as in production. Session bootstrap uses `GET /api/v1/features` until E03 adds `/api/v1/me`; sign-in temporarily uses the Django admin login | |
| Frontend styling | Tailwind CSS v4; the `ui` package declares `@source "."` so its classes are generated in consuming apps | Workspace symlinks are skipped by Tailwind scanning |
| API client | `createApiClient()` resolves `fetch` per call and uses absolute URLs | Needed for test stubs and instrumentation |
| Infra (FR-01-16) | Terraform baseline passes `terraform validate` but is **not applied**; the deploy workflow needs the AWS OIDC role, ECR and state bucket first | No AWS account configured yet |
| Windows dev | `make` is not installed by default: `winget install ezwinports.make`, or run the Makefile commands directly | |

### Verified
- Backend: 123 tests (incl. thread-concurrency tests for the outbox and sequences, Hypothesis money properties, DST recurrence), 93% coverage, ruff and mypy clean, `check --deploy` clean, OpenAPI schema validates with zero warnings.
- Frontend: lint, typecheck, unit tests and production builds pass for all 6 packages.
- End to end on the local stack: upload, S3 PUT, complete, Celery scan, presigned download (bytes match); the admin app signs in on `brightminds.localhost` and loads features and the audit log grid.
- Production Docker image builds.

### Carried forward
- **E02:** RLS policies + `enable_rls` migration helper + non-owner DB role; `BranchScopedModel`; full tenant resolver; set `app.current_org` in `TenantTask`.
- **E03:** replace `has_perm`, the Django-admin sign-in and the `/features` session probe (add `/api/v1/me`).
- **E29:** `core.crypto.EncryptedField`; ClamAV service in the AWS stack.
- **E32:** Temporal takes over long-running processes; Celery stays for short tasks (outbox dispatch, sends, scans, webhooks, global crons).
- **E30:** alarms, dashboards and the dead-letter console on top of `core.events.dispatcher.replay_dead_letter`.
- Not yet in CI: Storybook build. The Playwright e2e job is defined and runs on pushes to `main` only.
