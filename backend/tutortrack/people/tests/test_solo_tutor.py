"""Sole traders are the only tutor (ADR 0045): solo mode refuses a second tutor, tutor
invitations and the switch to "Sole trader" while there is a team; /me names the owner's own
tutor record for "My tutor profile"."""

from __future__ import annotations

import pytest

from tutortrack.core.context import branch_scope, tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people import services
from tutortrack.people.models import TutorProfile
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.tenancy.models import Organisation
from tutortrack.tenancy.services import update_organisation

pytestmark = pytest.mark.django_db


@pytest.fixture
def solo(org):
    update_organisation(org, business_type=Organisation.BusinessType.SOLE_TRADER)
    org.refresh_from_db()
    assert org.mode == Organisation.Mode.SOLO
    return org


def test_a_sole_trader_adds_themselves_then_cannot_add_another_tutor(solo, api):
    assert api.post("/api/v1/tutors/add-me").status_code == 200
    refused = api.post(
        "/api/v1/tutors", {"email": "nia@example.com", "first_name": "Nia"}, format="json"
    )
    assert refused.status_code == 422, refused.json()
    assert "sole trader" in refused.json()["detail"]
    assert "sole trader" in refused.json()["errors"]["email"][0]
    with tenant_context(solo):
        assert TutorProfile.objects.count() == 1


def test_a_sole_trader_who_does_not_teach_yet_can_add_one_tutor(solo, api, user):
    added = api.post("/api/v1/tutors", {"email": user.email, "first_name": "Me"}, format="json")
    assert added.status_code == 201, added.json()
    # Adding yourself afterwards links that record instead of making a second one.
    assert api.post("/api/v1/tutors/add-me").json()["id"] == added.json()["id"]


def test_a_sole_trader_cannot_invite_someone_as_a_tutor(solo, api):
    refused = api.post(
        "/api/v1/invitations", {"email": "sam@example.com", "role": "tutor"}, format="json"
    )
    assert refused.status_code == 422, refused.json()
    assert "sole trader" in refused.json()["detail"]
    # Other roles (a bookkeeper, say) are still fine.
    invited = api.post(
        "/api/v1/invitations", {"email": "books@example.com", "role": "finance"}, format="json"
    )
    assert invited.status_code == 201, invited.json()


def test_a_sole_trader_cannot_reactivate_a_second_tutor(solo):
    with tenant_context(solo):
        mine = TutorProfileFactory(organisation=solo, status=TutorProfile.Status.ACTIVE)
        old = TutorProfileFactory(organisation=solo, status=TutorProfile.Status.INACTIVE)
        with pytest.raises(BusinessRuleViolation, match="sole trader"):
            services.change_tutor_status(old, TutorProfile.Status.ACTIVE)
        # Their own record can come back once it is the only one.
        services.change_tutor_status(mine, TutorProfile.Status.INACTIVE)
        services.change_tutor_status(mine, TutorProfile.Status.ACTIVE)


def test_a_team_adds_as_many_tutors_as_the_plan_allows(org):
    with tenant_context(org):
        services.create_tutor(email="nia@example.com", first_name="Nia", invite=False)
        services.create_tutor(email="sam@example.com", first_name="Sam", invite=False)
        assert TutorProfile.objects.count() == 2


def test_a_team_cannot_become_a_sole_trader_while_it_has_several_tutors(org, api):
    with tenant_context(org):
        TutorProfileFactory(organisation=org, status=TutorProfile.Status.ACTIVE)
        second = TutorProfileFactory(organisation=org, status=TutorProfile.Status.ONBOARDING)
    refused = api.patch("/api/v1/organisation", {"business_type": "sole_trader"}, format="json")
    assert refused.status_code == 422, refused.json()
    assert "more than one tutor" in refused.json()["errors"]["business_type"][0]
    org.refresh_from_db()
    assert org.mode == Organisation.Mode.MULTI
    # With the other tutor archived, the switch goes through.
    with tenant_context(org):
        services.change_tutor_status(second, TutorProfile.Status.ARCHIVED)
    switched = api.patch("/api/v1/organisation", {"business_type": "sole_trader"}, format="json")
    assert switched.status_code == 200, switched.json()
    org.refresh_from_db()
    assert org.mode == Organisation.Mode.SOLO


def test_me_names_your_own_tutor_record(org, api):
    assert api.get("/api/v1/me").json()["membership"]["tutor_id"] is None
    mine = api.post("/api/v1/tutors/add-me").json()
    assert api.get("/api/v1/me").json()["membership"]["tutor_id"] == mine["id"]


def test_sample_data_for_a_sole_trader_uses_their_own_tutor_record(solo, member):
    from tutortrack.scheduling.models import Lesson
    from tutortrack.tenancy import demo

    MembershipFactory(organisation=solo, role=Membership.Role.OWNER)
    with tenant_context(solo), branch_scope(None):
        mine = services.add_self_as_tutor(member)
        demo.load_demo_data()
        assert list(TutorProfile.objects.values_list("pk", flat=True)) == [mine.pk]
        assert Lesson.objects.exists()
        assert set(Lesson.objects.values_list("tutors__tutor", flat=True)) - {None} == {mine.pk}


def test_sample_data_for_a_sole_trader_who_does_not_teach_makes_one_tutor(solo):
    from tutortrack.tenancy import demo

    MembershipFactory(organisation=solo, role=Membership.Role.OWNER)
    with tenant_context(solo), branch_scope(None):
        demo.load_demo_data()
        assert TutorProfile.objects.count() == 1
