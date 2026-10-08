from collections.abc import Iterator
from typing import Any

import fakeredis
import pytest
from django.conf import settings

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import client_for
from tutortrack.identity.tests.factories import UserFactory
from tutortrack.tenancy.models import Organisation
from tutortrack.tenancy.tests.factories import OrganisationFactory


@pytest.fixture
def org(db: None) -> Organisation:
    return OrganisationFactory(name="Bright Minds", slug="brightminds")


@pytest.fixture
def other_org(db: None) -> Organisation:
    return OrganisationFactory(name="Other Tutors", slug="othertutors")


@pytest.fixture
def tenant(org: Organisation) -> Iterator[Organisation]:
    """Run the test body inside ``org``'s tenant context."""
    with tenant_context(org):
        yield org


@pytest.fixture
def user(db: None) -> Any:
    return UserFactory()


@pytest.fixture
def superuser(db: None) -> Any:
    return UserFactory(is_superuser=True, is_staff=True)


@pytest.fixture
def api(org: Organisation, user: Any) -> Any:
    """Logged-in API client for ``org``."""
    return client_for(org, user)


@pytest.fixture
def admin_api(org: Organisation, superuser: Any) -> Any:
    return client_for(org, superuser)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeRedis:
    server = fakeredis.FakeRedis()
    monkeypatch.setattr("tutortrack.core.redis.get_redis", lambda: server)
    monkeypatch.setattr("tutortrack.core.tasks.get_redis", lambda: server)
    monkeypatch.setattr("tutortrack.core.api.health.get_redis", lambda: server)
    return server


@pytest.fixture
def s3() -> Iterator[Any]:
    """In-memory S3 (moto) with the configured bucket created."""
    from moto import mock_aws

    from tutortrack.core.storage.client import reset_clients, s3_client

    with mock_aws():
        reset_clients()
        client = s3_client()
        client.create_bucket(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            CreateBucketConfiguration={"LocationConstraint": settings.AWS_S3_REGION_NAME},
        )
        yield client
    reset_clients()


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()
