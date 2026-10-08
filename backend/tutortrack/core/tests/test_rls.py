"""Postgres row-level security (FR-02-4): the database itself isolates tenants, even for
raw SQL and for code that forgets the ORM tenant filter."""

from __future__ import annotations

import pathlib
import re

import pytest
from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.db import ProgrammingError, connection, transaction

from tutortrack.core.context import request_context, tenant_context
from tutortrack.core.db import PLATFORM_DB_ALIAS
from tutortrack.core.models import TenantModel
from tutortrack.core.tasks import TenantTask

from .factories import GadgetFactory
from .testapp.models import Gadget

pytestmark = pytest.mark.django_db


def raw_gadget_names() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM testapp_gadget")
        return {row[0] for row in cursor.fetchall()}


@pytest.fixture
def gadgets(org, other_org):
    return GadgetFactory(organisation=org, name="mine"), GadgetFactory(
        organisation=other_org, name="theirs"
    )


def test_raw_sql_without_tenant_returns_zero_rows(gadgets):
    """AC: a raw SELECT from the app role without app.current_org set returns nothing."""
    assert raw_gadget_names() == set()


def test_raw_sql_sees_only_the_tenant_in_context(gadgets, org, other_org):
    with tenant_context(org):
        assert raw_gadget_names() == {"mine"}
    with tenant_context(other_org):
        assert raw_gadget_names() == {"theirs"}
    assert raw_gadget_names() == set()


def test_unscoped_orm_query_is_still_bounded_by_rls(gadgets, org):
    with tenant_context(org):
        assert set(Gadget.all_tenants.values_list("name", flat=True)) == {"mine"}


def test_cannot_insert_rows_for_another_tenant(org, other_org):
    with (
        tenant_context(org),
        pytest.raises(ProgrammingError, match="row-level security"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "INSERT INTO testapp_gadget (id, organisation_id, name, created_at, updated_at) "
            "VALUES (gen_random_uuid(), %s, 'sneaky', now(), now())",
            [other_org.pk],
        )


def test_cannot_move_a_row_to_another_tenant(gadgets, org, other_org):
    mine, _ = gadgets
    with (
        tenant_context(org),
        pytest.raises(ProgrammingError, match="row-level security"),
        transaction.atomic(),
    ):
        Gadget.all_tenants.filter(pk=mine.pk).update(organisation_id=other_org.pk)


def test_session_variable_follows_rollbacks(gadgets, org, other_org):
    """A value set inside a rolled-back transaction is reverted by Postgres; the cached
    value must not survive it (or the next transaction would run with the wrong tenant)."""
    with tenant_context(org):
        with pytest.raises(RuntimeError), transaction.atomic():
            assert raw_gadget_names() == {"mine"}
            raise RuntimeError
        with transaction.atomic():
            assert raw_gadget_names() == {"mine"}
    with tenant_context(other_org), transaction.atomic():
        assert raw_gadget_names() == {"theirs"}


def test_session_variable_follows_savepoint_rollbacks(gadgets, org):
    with transaction.atomic():
        with pytest.raises(RuntimeError), transaction.atomic(), tenant_context(org):
            assert raw_gadget_names() == {"mine"}
            raise RuntimeError
        with tenant_context(org):
            assert raw_gadget_names() == {"mine"}
        assert raw_gadget_names() == set()


def test_current_user_session_variable_is_set(user):
    with request_context(user_id=user.pk), connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('app.current_user', true)")
        assert cursor.fetchone()[0] == str(user.pk)


rls_seen: list[set[str]] = []


@shared_task(base=TenantTask, name="tests.rls_probe")
def rls_probe(*, organisation_id: str) -> None:
    rls_seen.append(raw_gadget_names())


def test_celery_tenant_tasks_run_under_rls(gadgets, org):
    rls_seen.clear()
    rls_probe.delay(organisation_id=str(org.pk))
    assert rls_seen == [{"mine"}]


@pytest.mark.django_db(databases=["default", PLATFORM_DB_ALIAS], transaction=True)
def test_platform_connection_bypasses_rls(org, other_org):
    GadgetFactory(organisation=org, name="mine")
    GadgetFactory(organisation=other_org, name="theirs")
    names = set(Gadget.all_tenants.using(PLATFORM_DB_ALIAS).values_list("name", flat=True))
    assert names == {"mine", "theirs"}


def test_app_role_is_subject_to_rls():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
        )
        user, is_super, bypass = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = %s",
            [user],
        )
        owned = cursor.fetchone()[0]
    assert user == settings.DB_APP_ROLE[0]
    assert (is_super, bypass, owned) == (False, False, 0)


def test_every_tenant_table_has_an_rls_policy():
    """Guards CLAUDE.md rule 9: new TenantModel tables must call enable_rls()."""
    tables = sorted(
        m._meta.db_table
        for m in apps.get_models()
        if issubclass(m, TenantModel) and not m._meta.proxy and m._meta.managed
    )
    assert tables, "expected tenant tables"
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_policies p ON p.tablename = c.relname "
            "WHERE c.relrowsecurity AND p.policyname = 'tenant_isolation' "
            "AND c.relname = ANY(%s)",
            [tables],
        )
        protected = {row[0] for row in cursor.fetchall()}
    assert sorted(set(tables) - protected) == []


ALLOWED_PLATFORM_ALIAS_USERS = ("platform_admin/", "core/db.py", "core/dbroles.py", "/tests/")


def test_platform_alias_is_only_used_by_platform_admin_code():
    """FR-02-4: the BYPASSRLS connection is only reachable from platform_admin."""
    root = pathlib.Path(__file__).resolve().parents[2]
    pattern = re.compile(r"PLATFORM_DB_ALIAS|using\(\s*[\"']platform[\"']")
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if not any(part in str(path.relative_to(root)) for part in ALLOWED_PLATFORM_ALIAS_USERS)
        and pattern.search(path.read_text())
    ]
    assert offenders == []
