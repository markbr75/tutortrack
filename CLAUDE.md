# CLAUDE.md — TutorTrack engineering rules

TutorTrack is a multi-tenant SaaS for running tutoring businesses. Specs live in `docs/`. **Read `docs/02-architecture.md` and `docs/03-domain-model.md` before any work.** Build tickets come from `docs/epics/EXX-*.md` → "Delivery Plan".

## Stack
Python 3.12 · Django 5 · DRF + drf-spectacular · PostgreSQL 16 · Celery + Redis · React 18 + TypeScript + Vite + TanStack Query + Tailwind/shadcn · pytest · Playwright.

## Commands
- `make dev`: start the full stack (docker-compose)
- `make test`: backend and frontend tests
- `make check`: ruff, mypy, eslint, tsc, tests, `makemigrations --check`, OpenAPI drift check. **Must pass before a ticket is done.**
- `make api-client`: regenerate the TS client from OpenAPI

## Non-negotiables
1. **Tenancy:** every tenant-owned model subclasses `core.models.TenantModel`. Never query with `all_tenants` outside `platform_admin`. Every new list/detail endpoint gets a cross-tenant isolation test (`TenantIsolationTestMixin`).
2. **Business logic lives in `services.py`** (writes) and `selectors.py` (reads). Views and serializers stay thin. Apps talk to each other via services and domain events, never by writing to another app's models.
3. **Domain events:** emit via `core.events.publish()` inside the transaction (outbox). Handlers must be idempotent.
4. **Audit:** mutations go through services, which record `AuditEntry`.
5. **Money:** use `core.money.Money` / `Decimal` only, never float. Round half-up to the currency minor unit at line level. Financial records are never deleted or edited after issue: use credit notes and adjustments.
6. **Time:** store UTC (`timestamptz`); carry IANA timezone on lessons, users, branches and orgs. Recurrence expands in the lesson's local tz.
7. **Permissions:** declare codenames in `<app>/permissions.py`; enforce in API permission classes *and* queryset scoping. Sensitive fields are hidden by serializer field-permission mixins.
8. **API:** `/api/v1/`, cursor pagination, RFC 7807 errors, `Idempotency-Key` on financial POSTs, OpenAPI documented with examples.
9. **Migrations:** backward compatible (expand/contract). Add RLS policies for new tenant tables via `core.migrations_utils.enable_rls`.
10. **Tests first:** every FR in the ticket gets a test. Use `factory_boy` factories in `<app>/tests/factories.py`. Use Hypothesis for money, recurrence and proration logic.
11. **Secrets/PII:** OAuth tokens, bank details and safeguarding notes use `core.crypto.EncryptedField`. Never log PII or tokens.
12. **i18n:** wrap user-facing strings (`gettext` / `t()`). No hard-coded currency symbols or date formats.
13. **Accessibility:** WCAG 2.2 AA for all UI.

## Ticket workflow
1. Read the epic and ticket, then restate the acceptance criteria.
2. Write or extend models, migrations, services, selectors, API and tests; then frontend.
3. Run `make check`.
4. Update the epic's ticket checkbox and add an ADR in `docs/adr/` for any significant decision.
