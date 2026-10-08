from datetime import timedelta

import pytest

from tutortrack.core import flags
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import FeatureDisabled
from tutortrack.core.models import FeatureFlag, FeatureFlagOverride
from tutortrack.core.time import now

pytestmark = pytest.mark.django_db


@pytest.fixture
def courses():
    return FeatureFlag.objects.create(key="courses", enabled_globally=False, plan_keys=["agency"])


def test_unknown_flags_are_off(org):
    assert not flags.is_enabled("does-not-exist", org.pk)


def test_global_default(courses, org):
    assert not flags.is_enabled("courses", org.pk)
    courses.enabled_globally = True
    courses.save()
    assert flags.is_enabled("courses", org.pk)


def test_org_override_wins_and_expires(courses, org, other_org):
    override = FeatureFlagOverride.objects.create(flag=courses, organisation=org, enabled=True)
    assert flags.is_enabled("courses", org.pk)
    assert not flags.is_enabled("courses", other_org.pk)

    override.expires_at = now() - timedelta(minutes=1)
    override.save()
    assert not flags.is_enabled("courses", org.pk)


def test_plan_resolution(courses, org, monkeypatch):
    monkeypatch.setattr(flags, "PLAN_RESOLVER", "tutortrack.core.tests.test_flags.agency_plan")
    assert flags.is_enabled("courses", org.pk)


def agency_plan(organisation_id):
    return "agency"


def test_uses_tenant_in_context(courses, org):
    FeatureFlagOverride.objects.create(flag=courses, organisation=org, enabled=True)
    with tenant_context(org):
        assert flags.is_enabled("courses")
    assert not flags.is_enabled("courses")


def test_requires_feature_decorator(courses, org):
    @flags.requires_feature("courses")
    def create_course() -> str:
        return "created"

    with tenant_context(org):
        with pytest.raises(FeatureDisabled):
            create_course()
        FeatureFlagOverride.objects.create(flag=courses, organisation=org, enabled=True)
        assert create_course() == "created"


def test_features_endpoint(courses, org, api):
    FeatureFlag.objects.create(key="payroll", enabled_globally=True)
    FeatureFlagOverride.objects.create(flag=courses, organisation=org, enabled=True)
    assert api.get("/api/v1/features").json() == {"features": {"courses": True, "payroll": True}}
