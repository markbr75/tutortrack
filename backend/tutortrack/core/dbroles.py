"""Create the application and platform database roles and grant them table privileges.

Run as the owner/migration role (``manage.py ensure_db_roles``; ``migrate`` re-grants after
every run through ``post_migrate``). Everything here is idempotent.

* App role: ``LOGIN NOSUPERUSER NOBYPASSRLS``; SELECT/INSERT/UPDATE/DELETE on every table,
  except the append-only audit table (SELECT/INSERT only). No TRUNCATE outside tests.
* Platform role: ``LOGIN BYPASSRLS``; full DML. Creating a BYPASSRLS role needs a
  superuser (or, on managed Postgres, the provider's admin role).
"""

from __future__ import annotations

import time
from typing import Any

from django.conf import settings
from django.db import IntegrityError, InternalError, ProgrammingError, connections, transaction
from psycopg import sql

from .db import OWNER_DB_ALIAS, PLATFORM_DB_ALIAS

APPEND_ONLY_TABLES = ("core_auditentry",)
_LOCK_KEY = 7_300_201  # pg_advisory_xact_lock id: serialises concurrent role setup


def role_credentials(alias: str) -> tuple[str, str]:
    db = settings.DATABASES.get(alias) or {}
    return str(db.get("USER", "")), str(db.get("PASSWORD", ""))


def app_role_credentials() -> tuple[str, str]:
    override = getattr(settings, "DB_APP_ROLE", None)
    if override:
        return str(override[0]), str(override[1])
    return role_credentials("default")


def platform_role_credentials() -> tuple[str, str]:
    return role_credentials(PLATFORM_DB_ALIAS)


def _ensure_role(
    cursor: Any, name: str, password: str, *, bypass_rls: bool, update_existing: bool
) -> bool:
    attrs = "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE " + (
        "BYPASSRLS" if bypass_rls else "NOBYPASSRLS"
    )
    cursor.execute(
        "SELECT rolcanlogin AND NOT rolsuper AND rolbypassrls = %s FROM pg_roles "
        "WHERE rolname = %s",
        [bypass_rls, name],
    )
    row = cursor.fetchone()
    if row is not None and row[0] and not update_existing:
        return False  # already correct; avoid cluster-wide catalog writes
    verb = "ALTER" if row is not None else "CREATE"
    cursor.execute(
        sql.SQL("{} ROLE {} WITH " + attrs + " PASSWORD {}").format(
            sql.SQL(verb), sql.Identifier(name), sql.Literal(password)
        )
    )
    return row is None


def ensure_roles(using: str = OWNER_DB_ALIAS, *, update_existing: bool = True) -> list[str]:
    """Create (or, with ``update_existing``, reset) both roles. Returns the roles created.

    Roles are cluster-wide while advisory locks are per database, so concurrent callers
    on different databases (parallel test workers) can still collide: those attempts are
    retried.
    """
    created: list[str] = []
    app_user, app_password = app_role_credentials()
    platform_user, platform_password = platform_role_credentials()
    connection = connections[using]
    owner = connection.settings_dict["USER"]
    for name, password, bypass in (
        (app_user, app_password, False),
        (platform_user, platform_password, True),
    ):
        if not name or name == owner:
            continue  # single-role setups (e.g. a throwaway CI database)
        for attempt in range(5):
            try:
                with transaction.atomic(using=using), connection.cursor() as cursor:
                    if _ensure_role(
                        cursor, name, password, bypass_rls=bypass, update_existing=update_existing
                    ):
                        created.append(name)
                break
            except (IntegrityError, InternalError, ProgrammingError):
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
    return created


def _role_exists(cursor: Any, name: str) -> bool:
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [name])
    return cursor.fetchone() is not None


def grant_privileges(using: str = OWNER_DB_ALIAS, *, truncate: bool | None = None) -> None:
    """Grant DML on every table and sequence in ``public`` (and future ones) to the roles."""
    if truncate is None:
        truncate = bool(getattr(settings, "DB_GRANT_TRUNCATE", False))
    app_user, _ = app_role_credentials()
    platform_user, _ = platform_role_credentials()
    connection = connections[using]
    owner = connection.settings_dict["USER"]
    dml = "SELECT, INSERT, UPDATE, DELETE" + (", TRUNCATE" if truncate else "")
    with transaction.atomic(using=using), connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_KEY])
        for role in {app_user, platform_user} - {owner, ""}:
            if not _role_exists(cursor, role):
                continue
            ident = sql.Identifier(role)
            for stmt in (
                f"GRANT {dml} ON ALL TABLES IN SCHEMA public TO {{}}",
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}",
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT {dml} ON TABLES TO {{}}",
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}",
            ):
                cursor.execute(sql.SQL(stmt).format(ident))
        if app_user and app_user != owner and _role_exists(cursor, app_user):
            for table in APPEND_ONLY_TABLES:
                cursor.execute("SELECT to_regclass(%s)", [table])
                if cursor.fetchone()[0] is None:
                    continue
                cursor.execute(
                    sql.SQL("REVOKE UPDATE, DELETE ON {} FROM {}").format(
                        sql.Identifier(table), sql.Identifier(app_user)
                    )
                )
