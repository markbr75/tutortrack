"""Database plumbing for Postgres row-level security (docs/02-architecture.md §3, FR-02-4).

Three roles, three aliases:

* ``default`` connects as the **application role** (``tutortrack_app``): not the table
  owner, ``NOBYPASSRLS``, so every RLS policy applies to it.
* ``owner`` connects as the **migration role** that owns the tables. ``manage.py migrate``
  uses it automatically (see ``core/management/commands/migrate.py``).
* ``platform`` connects as a ``BYPASSRLS`` role for platform-admin code only (E30). Use it
  explicitly with ``.using(PLATFORM_DB_ALIAS)``; nothing else may import it (enforced by a
  test).

The policies compare ``organisation_id`` with the session variable ``app.current_org``.
``RLSSessionWrapper`` keeps that variable (and ``app.current_user``) equal to the tenant and
request context *before every query*, so it works in autocommit mode, inside transactions,
in Celery tasks and in tests without callers having to remember anything. The value is
cached per connection and only re-sent when it changes (or after a rollback), so the cost
is one extra statement per change of tenant (normally once per request).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.signals import connection_created

from .context import current_organisation_id, get_request_context

logger = structlog.get_logger(__name__)

PLATFORM_DB_ALIAS = "platform"
OWNER_DB_ALIAS = "owner"

ORG_SETTING = "app.current_org"
USER_SETTING = "app.current_user"

_UNKNOWN = object()
_SET_SQL = f"SELECT set_config('{ORG_SETTING}', %s, false), set_config('{USER_SETTING}', %s, false)"


def rls_aliases() -> list[str]:
    """Aliases whose connections carry the tenant session variables."""
    aliases: list[str] = getattr(settings, "RLS_DB_ALIASES", ["default"])
    return aliases


def desired_session_values() -> tuple[str, str]:
    org_id = current_organisation_id()
    user_id = get_request_context().user_id
    return (str(org_id) if org_id else "", str(user_id) if user_id else "")


class RLSSessionWrapper:
    """``connection.execute_wrappers`` entry that syncs the RLS session variables.

    The variables are set at *session* level and cached on the connection. Postgres
    reverts a ``set_config`` made inside a transaction (or savepoint) that rolls back, so
    ``install_rls_wrapper`` also hooks the connection's rollback methods to drop the cache.
    """

    def __call__(
        self,
        execute: Callable[..., Any],
        sql: str,
        params: Any,
        many: bool,
        context: dict[str, Any],
    ) -> Any:
        conn: BaseDatabaseWrapper = context["connection"]
        if isinstance(sql, str) and sql.lstrip()[:8].upper() == "ROLLBACK":
            return execute(sql, params, many, context)  # may run in an aborted transaction
        wanted = desired_session_values()
        if conn.__dict__.get("_tt_rls_value", _UNKNOWN) != wanted:
            context["cursor"].cursor.execute(_SET_SQL, wanted)
            conn.__dict__["_tt_rls_value"] = wanted
        return execute(sql, params, many, context)


_wrapper = RLSSessionWrapper()


def _forget_on(connection: BaseDatabaseWrapper, method: str) -> None:
    original = getattr(connection, method)
    if getattr(original, "_tt_rls_hook", False):
        return

    def hooked(*args: Any, **kwargs: Any) -> Any:
        try:
            return original(*args, **kwargs)
        finally:
            connection.__dict__["_tt_rls_value"] = _UNKNOWN

    hooked._tt_rls_hook = True  # type: ignore[attr-defined]
    setattr(connection, method, hooked)


def install_rls_wrapper(sender: Any, connection: BaseDatabaseWrapper, **_: Any) -> None:
    """``connection_created`` receiver: attach the wrapper and verify the role."""
    if connection.vendor != "postgresql" or connection.alias not in rls_aliases():
        return
    connection.__dict__["_tt_rls_value"] = _UNKNOWN
    if _wrapper not in connection.execute_wrappers:
        connection.execute_wrappers.append(_wrapper)
    for method in ("_rollback", "_savepoint_rollback"):
        _forget_on(connection, method)
    _check_role(connection)


def _check_role(connection: BaseDatabaseWrapper) -> None:
    """The app role must be subject to RLS: not a superuser and not BYPASSRLS."""
    mode = getattr(settings, "DB_RLS_ROLE_CHECK", "warn")
    if mode == "off":
        return
    with connection.connection.cursor() as cursor:  # raw cursor: no wrappers, no recursion
        cursor.execute(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        row = cursor.fetchone()
    if row is None or not (row[1] or row[2]):
        return
    message = (
        f"Database role {row[0]!r} bypasses row-level security (superuser or BYPASSRLS). "
        "Point DATABASE_URL at the application role (see `manage.py ensure_db_roles`)."
    )
    if mode == "error":
        raise ImproperlyConfigured(message)
    logger.warning("db.rls_role_bypasses_rls", role=row[0])


def connect_signals() -> None:
    connection_created.connect(install_rls_wrapper, dispatch_uid="tutortrack.core.db.rls")


class DatabaseRouter:
    """Only the owner/default aliases run migrations; ``platform`` never does."""

    def allow_migrate(self, db: str, app_label: str, **hints: Any) -> bool | None:
        if db == PLATFORM_DB_ALIAS:
            return False
        return None
