"""Dev seed: one sign-in per role for manual testing and the Playwright journeys, and a
second organisation for tenant-isolation checks (docs/test-plan/README.md).

Every account uses the shared seed password (``SEED_ADMIN_PASSWORD``, default
``tutortrack``). The owner is ``admin@tutortrack.localhost`` from ``core.seeds``.
"""

from __future__ import annotations

import os
from typing import Any

from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step
from tutortrack.core.time import now

DOMAIN = "tutortrack.localhost"
OTHER_ORG_SLUG = "northside"
OTHER_OWNER_EMAIL = "owner@northside.localhost"

# (email, role, first name, last name, title)
STAFF = [
    (f"office@{DOMAIN}", "admin", "Olivia", "Office", "Office manager"),
    (f"manager@{DOMAIN}", "branch_manager", "Marcus", "Manager", "Branch manager"),
    (f"coordinator@{DOMAIN}", "coordinator", "Chloe", "Coordinator", "Tuition coordinator"),
    (f"finance@{DOMAIN}", "finance", "Faisal", "Finance", "Accounts"),
]


def _password() -> str:
    return os.environ.get("SEED_ADMIN_PASSWORD", "tutortrack")


def _user(email: str, first_name: str, last_name: str, **extra: Any) -> Any:
    """The login for ``email``, created verified with the seed password (no validators:
    the shared dev password is deliberately simple)."""
    from tutortrack.identity.models import User

    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(
            email,
            _password(),
            first_name=first_name,
            last_name=last_name,
            email_verified_at=now(),
            **extra,
        )
    return user


def _member(user: Any, role: str, **kwargs: Any) -> Any:
    from tutortrack.identity.models import Membership
    from tutortrack.identity.services import add_member

    membership = Membership.objects.filter(user=user).first()
    return membership or add_member(user, role=role, **kwargs)


@seed_step(order=94)
def role_accounts(ctx: SeedContext) -> None:
    from tutortrack.growth.models import Affiliate
    from tutortrack.growth.services import link_affiliate_user
    from tutortrack.identity.models import Membership
    from tutortrack.people.models import Contact, Student, TutorProfile
    from tutortrack.people.services import link_membership, link_portal_user
    from tutortrack.tenancy.models import Branch

    with tenant_context(ctx.organisation), transaction.atomic():
        branch = Branch.objects.filter(is_default=True).first()
        for email, role, first, last, title in STAFF:
            user = _user(email, first, last)
            if role == "branch_manager" and branch is not None:
                _member(
                    user,
                    role,
                    branch_scope=Membership.BranchScope.SELECTED,
                    branches=[branch],
                    title=title,
                )
            else:
                _member(user, role, title=title)

        tutor = TutorProfile.objects.filter(email="nia.adeyemi@example.com").first()
        if tutor is not None:
            user = _user(f"tutor@{DOMAIN}", tutor.first_name, tutor.last_name)
            link_membership(tutor, _member(user, "tutor", title="Tutor"))

        contact = Contact.objects.filter(email="priya.patel@example.com").first()
        if contact is not None:
            user = _user(f"parent@{DOMAIN}", contact.first_name, contact.last_name)
            _member(user, "client")
            link_portal_user("people.contact", str(contact.pk), user)

        student = Student.objects.filter(first_name="Arjun").first()
        if student is not None:
            user = _user(f"student@{DOMAIN}", student.first_name, student.last_name)
            _member(user, "student")
            link_portal_user("people.student", str(student.pk), user)

        affiliate = Affiliate.objects.filter(name="Hillside Primary PTA").first()
        if affiliate is not None:
            user = _user(f"affiliate@{DOMAIN}", "Hillside", "PTA")
            _member(user, "affiliate")
            link_affiliate_user(str(affiliate.pk), user)

    _user(f"platform@{DOMAIN}", "Platform", "Staff", is_platform_staff=True)
    ctx.log("    role accounts: office, manager, coordinator, finance, tutor, parent, student,")
    ctx.log(f"    affiliate and platform @{DOMAIN} (password from SEED_ADMIN_PASSWORD)")


@seed_step(order=98)
def isolation_organisation(ctx: SeedContext) -> None:
    """A second tenant: nothing of Northside's may ever show up for Bright Minds users."""
    from tutortrack.people import services as people
    from tutortrack.people.models import Client
    from tutortrack.tenancy.models import Organisation
    from tutortrack.tenancy.services import create_organisation

    owner = _user(OTHER_OWNER_EMAIL, "Nadia", "North")
    org = Organisation.objects.filter(slug=OTHER_ORG_SLUG).first()
    if org is None:
        org = create_organisation(
            name="Northside Learning",
            slug=OTHER_ORG_SLUG,
            owner=owner,
            country="GB",
            business_type=Organisation.BusinessType.AGENCY,
            status=Organisation.Status.ACTIVE,
        )
    with tenant_context(org), transaction.atomic():
        if not Client.objects.exists():
            people.quick_add_family(
                contact={
                    "first_name": "Olivia",
                    "last_name": "Northside",
                    "email": "olivia.northside@example.com",
                },
                students=[{"first_name": "Noah", "year_group": "Year 9"}],
            )
    ctx.log(f"    second organisation {org.name} -> {org.base_url} ({OTHER_OWNER_EMAIL})")
