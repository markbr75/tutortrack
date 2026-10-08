"""E02-T01: organisations, default branch, slug rules, branches (FR-02-1, FR-02-2)."""

from datetime import timedelta

import pytest

from tutortrack.core.context import request_context, tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation, FeatureDisabled
from tutortrack.core.models import AuditEntry, FeatureFlag, OutboxEvent
from tutortrack.core.time import now
from tutortrack.identity.models import Membership
from tutortrack.identity.tests.factories import UserFactory
from tutortrack.tenancy import services, slugs
from tutortrack.tenancy.models import Branch, Organisation, OrganisationDomain
from tutortrack.tenancy.tests.factories import BranchFactory, OrganisationFactory

pytestmark = pytest.mark.django_db


def event_types(org) -> list[str]:
    return list(
        OutboxEvent.objects.filter(organisation_id=org.pk)
        .order_by("occurred_at", "id")
        .values_list("event_type", flat=True)
    )


@pytest.fixture
def multi_branch():
    FeatureFlag.objects.update_or_create(key="multi_branch", defaults={"enabled_globally": True})


# --- create_organisation --------------------------------------------------------------------------


def test_create_organisation_sets_up_default_branch_owner_and_events():
    owner = UserFactory(email="sam@example.com")
    org = services.create_organisation(
        name="Bright Minds", owner=owner, country="GB", business_type="agency"
    )

    assert org.slug == "bright-minds"
    assert org.status == Organisation.Status.TRIAL
    assert org.mode == Organisation.Mode.MULTI
    assert (org.default_currency, org.timezone, org.locale, org.region) == (
        "GBP", "Europe/London", "en-GB", "uk",
    )  # fmt: skip
    assert org.fiscal_year_start_month == 4
    assert org.created_by == owner
    with tenant_context(org):
        branch = Branch.objects.get()
        assert (branch.is_default, branch.code, branch.currency) == (True, "MAIN", "GBP")
        membership = Membership.objects.get()
        assert (membership.user, membership.role) == (owner, Membership.Role.OWNER)
        assert AuditEntry.objects.filter(object_type="tenancy.organisation").exists()
    assert event_types(org) == ["organisation.created", "branch.created"]


@pytest.mark.parametrize(
    ("country", "currency", "tz", "locale", "region", "week_start"),
    [
        ("US", "USD", "America/New_York", "en-US", "us", 6),
        ("AU", "AUD", "Australia/Sydney", "en-GB", "au", 0),
        ("FR", "EUR", "Europe/Paris", "en-GB", "eu", 0),
        ("PT", "EUR", "UTC", "en-GB", "eu", 0),
    ],
)
def test_country_drives_defaults(country, currency, tz, locale, region, week_start):
    org = services.create_organisation(name=f"Tutors {country}", owner=None, country=country)
    assert (org.default_currency, org.timezone, org.locale, org.region) == (
        currency, tz, locale, region,
    )  # fmt: skip
    assert org.week_start_day == week_start


def test_solo_business_types_use_solo_mode():
    org = services.create_organisation(name="Ann Tutor", owner=None, business_type="sole_trader")
    assert org.mode == Organisation.Mode.SOLO


def test_explicit_slug_and_overrides():
    org = services.create_organisation(
        name="Acme", owner=None, slug="Acme-Tutors", timezone="Europe/Paris", currency="eur"
    )
    assert (org.slug, org.timezone, org.default_currency) == ("acme-tutors", "Europe/Paris", "EUR")


def test_invalid_timezone_is_rejected():
    with pytest.raises(BusinessRuleViolation):
        services.create_organisation(name="Acme", owner=None, timezone="Mars/Olympus")


# --- slugs ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slug", ["ab", "-acme", "acme-", "ac--me", "Acme!", "a" * 64, "acme.tutors", "www", "api"]
)
def test_invalid_or_reserved_slugs_are_rejected(slug):
    with pytest.raises(slugs.InvalidSlug):
        services.create_organisation(name="Acme", owner=None, slug=slug)


def test_taken_slug_is_rejected_and_suggestions_avoid_it(org):
    with pytest.raises(slugs.InvalidSlug, match="taken"):
        services.create_organisation(name="Other", owner=None, slug=org.slug)
    assert slugs.suggest_slug("Bright Minds") == "bright-minds"
    OrganisationFactory(slug="bright-minds")
    assert slugs.suggest_slug("Bright Minds") == "bright-minds-2"


def test_short_names_get_a_valid_suggestion():
    assert slugs.slug_problem(slugs.suggest_slug("A")) is None
    assert slugs.slug_problem(slugs.suggest_slug("株式会社")) is None


def test_changing_slug_keeps_a_90_day_redirect(org, other_org):
    old = org.slug
    services.change_slug(org, "bright-new")
    org.refresh_from_db()
    assert org.slug == "bright-new"
    redirect = OrganisationDomain.objects.get(hostname=old)
    assert redirect.organisation == org
    assert redirect.redirect_until - now() > timedelta(days=89)
    # Another organisation cannot grab the old slug during the redirect window...
    assert "recently used" in slugs.slug_problem(old)
    with pytest.raises(slugs.InvalidSlug):
        services.change_slug(other_org, old)
    # ...but the original organisation can move back, which removes the redirect.
    services.change_slug(org, old)
    assert not OrganisationDomain.objects.filter(hostname=old).exists()
    assert OrganisationDomain.objects.filter(hostname="bright-new").exists()


def test_expired_redirects_free_the_slug(org, other_org):
    old = org.slug
    services.change_slug(org, "renamed")
    OrganisationDomain.objects.filter(hostname=old).update(redirect_until=now() - timedelta(1))
    services.change_slug(other_org, old)
    assert Organisation.objects.get(pk=other_org.pk).slug == old


def test_update_organisation_audits_and_publishes(org, user):
    with request_context(user_id=user.pk):
        services.update_organisation(org, legal_name="Bright Minds Ltd", business_type="agency")
    org.refresh_from_db()
    assert (org.legal_name, org.mode) == ("Bright Minds Ltd", Organisation.Mode.MULTI)
    with tenant_context(org):
        entry = AuditEntry.objects.filter(object_type="tenancy.organisation").latest("created_at")
    assert entry.changes["legal_name"] == ["", "Bright Minds Ltd"]
    assert entry.actor_id == user.pk
    assert "organisation.updated" in event_types(org)


def test_update_organisation_rejects_lifecycle_fields(org):
    with pytest.raises(BusinessRuleViolation):
        services.update_organisation(org, status="active")


# --- branches -------------------------------------------------------------------------------------


def test_extra_branches_need_the_multi_branch_feature(tenant):
    with pytest.raises(FeatureDisabled):
        services.create_branch(name="North", code="N")


def test_create_branch_inherits_org_defaults(tenant, multi_branch):
    branch = services.create_branch(name="North", code="n", currency="EUR")
    assert (branch.code, branch.currency, branch.timezone) == ("N", "EUR", tenant.timezone)
    assert not branch.is_default
    assert "branch.created" in event_types(tenant)


def test_branch_codes_are_unique_per_organisation(tenant, other_org, multi_branch):
    services.create_branch(name="North", code="N")
    with pytest.raises(BusinessRuleViolation):
        services.create_branch(name="Northern", code="n")
    BranchFactory(organisation=other_org, code="N")  # another org may reuse it


def test_only_one_default_branch_per_organisation(tenant):
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        BranchFactory(organisation=tenant, is_default=True)


def test_default_branch_cannot_be_archived(tenant):
    default = Branch.objects.get(is_default=True)
    with pytest.raises(BusinessRuleViolation):
        services.archive_branch(default)


def test_archive_and_update_branch(tenant, multi_branch):
    branch = services.create_branch(name="North", code="N")
    services.update_branch(branch, name="North Leeds", invoice_prefix="NL-")
    services.archive_branch(branch)
    branch.refresh_from_db()
    assert branch.name == "North Leeds"
    assert branch.is_archived
    assert {"branch.updated", "branch.archived"} <= set(event_types(tenant))
