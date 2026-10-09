# ADR 0003 — Postgres row-level security via session variables and three database roles

- **Status:** Accepted
- **Date:** 2026-10-09
- **Epic:** E02 (FR-02-3, FR-02-4)

## Context
ADR 0001 chose shared-schema multi-tenancy with an auto-scoping ORM manager plus Postgres
RLS as defence in depth. RLS only helps if (a) the application's database role is actually
subject to it, and (b) the tenant is reliably known to Postgres for every query, including
autocommit queries, Celery tasks and raw SQL.

The epic suggested `SET LOCAL app.current_org` per transaction (via `ATOMIC_REQUESTS` or a
wrapper). Django runs in autocommit by default, so `SET LOCAL` would be lost between
statements unless every request and task were wrapped in a transaction.

## Decision
1. **Three roles / aliases.** `default` = application role (not the owner, `NOBYPASSRLS`);
   `owner` = migration role that owns the tables (`manage.py migrate` targets it
   automatically); `platform` = `BYPASSRLS` role reachable only from platform-admin code.
   `manage.py ensure_db_roles` creates them; grants are re-applied after every migration.
2. **Session variables kept in sync by an execute wrapper.** Before each query on the
   `default` connection, `core.db.RLSSessionWrapper` compares the desired
   `(app.current_org, app.current_user)` with a per-connection cache and, only if different,
   sends `set_config(..., false)`. Because Postgres reverts `set_config` when a transaction
   or savepoint rolls back, the cache is invalidated after `_rollback` and
   `_savepoint_rollback`.
3. **Policies via `enable_rls()`** compare `organisation_id` with
   `NULLIF(current_setting('app.current_org', true), '')::uuid`; with no tenant the app role
   sees zero rows. Optional clauses allow a user's own rows across tenants and NULL-org
   inserts where needed.
4. **The test suite runs as the application role**, and meta-tests enforce that every
   `TenantModel` table has a policy and that the platform alias is not used elsewhere.

## Consequences
- Forgetting a tenant filter, using `all_tenants`, or writing raw SQL cannot leak or write
  another tenant's rows from the app role.
- Code that legitimately needs cross-tenant access must use the platform alias (E30) or a
  policy clause designed for it (e.g. memberships by user).
- One extra statement per change of tenant on a connection (normally once per request).
- Data migrations must use `schema_editor.connection.alias` (the owner connection);
  querying through the default connection inside a migration deadlocks against the owner's
  locks.
- Creating a `BYPASSRLS` role needs superuser-equivalent rights; managed Postgres setups
  must confirm this on first deploy.
