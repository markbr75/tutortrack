from unittest import mock

import pytest
from celery import shared_task

from tutortrack.core.context import current_organisation_id
from tutortrack.core.exceptions import NoTenantContext
from tutortrack.core.tasks import TenantTask, fan_out_per_org, singleton
from tutortrack.tenancy.models import Organisation
from tutortrack.tenancy.tests.factories import OrganisationFactory

seen: list[object] = []


@shared_task(base=TenantTask, name="tests.record_org")
def record_org(*, organisation_id: str) -> None:
    seen.append(current_organisation_id())


@pytest.fixture(autouse=True)
def _reset_seen():
    seen.clear()


@pytest.mark.django_db
def test_tenant_task_runs_inside_tenant_context(org):
    record_org.delay(organisation_id=str(org.pk))
    assert seen == [org.pk]
    assert current_organisation_id() is None  # context restored afterwards


def test_tenant_task_requires_organisation_id():
    with pytest.raises(NoTenantContext):
        record_org.apply(kwargs={}, throw=True)


@pytest.mark.django_db
def test_fan_out_targets_only_operational_organisations(org, other_org):
    OrganisationFactory(slug="gone", status=Organisation.Status.CANCELLED)
    with mock.patch.object(record_org, "apply_async") as apply_async:
        count = fan_out_per_org(record_org, run="nightly")
    assert count == 2
    called_orgs = {c.kwargs["kwargs"]["organisation_id"] for c in apply_async.call_args_list}
    assert called_orgs == {str(org.pk), str(other_org.pk)}
    assert all(c.kwargs["kwargs"]["run"] == "nightly" for c in apply_async.call_args_list)


def test_singleton_skips_when_lock_is_held(fake_redis):
    calls = []

    @singleton("nightly-job", timeout=60)
    def job() -> str:
        calls.append(1)
        return "ran"

    held = fake_redis.lock("lock:nightly-job", timeout=60)
    assert held.acquire(blocking=False)
    assert job() is None
    held.release()

    assert job() == "ran"
    assert calls == [1]
