# ADR 0001 — Core stack and multi-tenancy model

- **Status:** Accepted (initial; revisit before E01 starts if needed)
- **Date:** 2026-10-08

## Context
TutorTrack is a multi-tenant SaaS that must be built in Python on PostgreSQL. It is CRUD-heavy with complex finance, scheduling and permissions, and serves solo tutors up to 1,000-tutor agencies.

## Decision
1. **Django 5 + DRF** for the backend (not FastAPI): we get ORM, migrations, auth, admin, i18n and a mature permissions/filtering ecosystem out of the box.
2. **React + TypeScript SPA** for admin and portals, consuming the same public, versioned REST API (API-first).
3. **Shared-schema multi-tenancy** with `organisation_id` on every tenant row, an auto-scoping manager, and **Postgres RLS** as defence in depth. Not schema-per-tenant (migration cost at 10k tenants) and not DB-per-tenant (cost/ops).
4. **Transactional outbox** for domain events, feeding notifications, automations, webhooks and integrations.
5. **Append-only ledgers** for client and tutor money.

## Consequences
- Every query path must carry tenant context; enforced by the manager raising without context, RLS and mandatory isolation tests.
- Very large tenants share infrastructure; if needed later, a tenant can be moved to a dedicated regional stack (Organisation.region already exists).
- Two codebases (Python and TS) are kept in sync through the generated OpenAPI client, which is checked in CI.
