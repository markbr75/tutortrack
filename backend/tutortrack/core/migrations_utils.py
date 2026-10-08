"""Migration helpers.

Every new tenant table gets a row-level-security policy (CLAUDE.md rule 9)::

    from tutortrack.core.migrations_utils import enable_rls

    operations = [
        migrations.CreateModel(name="Invoice", ...),
        enable_rls("billing_invoice"),
    ]

The policy only lets the application role see and write rows whose ``organisation_id``
equals the ``app.current_org`` session variable (kept in sync by ``core.db``). Without a
tenant in context, the app role sees **zero rows**. The owner (migrations) and the
platform role (``BYPASSRLS``) are not restricted.
"""

from __future__ import annotations

from django.db import migrations

POLICY = "tenant_isolation"
CURRENT_ORG = "NULLIF(current_setting('app.current_org', true), '')::uuid"
CURRENT_USER = "NULLIF(current_setting('app.current_user', true), '')::uuid"


def rls_policy_sql(
    table: str,
    *,
    column: str = "organisation_id",
    user_column: str | None = None,
    allow_null_org_writes: bool = False,
) -> tuple[str, str]:
    """Forward and reverse SQL for the tenant isolation policy on ``table``.

    * ``user_column``: rows whose ``user_column`` equals ``app.current_user`` are also
      visible (e.g. a user's own memberships across organisations, for the org switcher).
    * ``allow_null_org_writes``: rows with a NULL organisation may be inserted (platform
      events such as signups in the audit log); they stay invisible to the app role.
    """
    using = f"{column} = {CURRENT_ORG}"
    if user_column:
        using = f"({using}) OR ({user_column} = {CURRENT_USER})"
    check = f"{column} = {CURRENT_ORG}"
    if allow_null_org_writes:
        check = f"({check}) OR ({column} IS NULL)"
    forward = (
        f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY;\n'
        f'DROP POLICY IF EXISTS {POLICY} ON "{table}";\n'
        f'CREATE POLICY {POLICY} ON "{table}" USING ({using}) WITH CHECK ({check});'
    )
    reverse = (
        f'DROP POLICY IF EXISTS {POLICY} ON "{table}";\n'
        f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY;'
    )
    return forward, reverse


def enable_rls(
    table: str,
    *,
    column: str = "organisation_id",
    user_column: str | None = None,
    allow_null_org_writes: bool = False,
) -> migrations.RunSQL:
    forward, reverse = rls_policy_sql(
        table,
        column=column,
        user_column=user_column,
        allow_null_org_writes=allow_null_org_writes,
    )
    return migrations.RunSQL(forward, reverse, elidable=False)
