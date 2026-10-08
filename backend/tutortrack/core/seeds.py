"""Core demo data: platform admin, the demo organisation and baseline feature flags.

Later epics extend the demo (branches, tutors, clients, students, lessons, invoices...)
from their own ``seeds.py`` with higher ``order`` values.
"""

import os

from tutortrack.core.models import FeatureFlag
from tutortrack.core.seeding import SeedContext, seed_step

DEMO_ORG_SLUG = "brightminds"
ADMIN_EMAIL = "admin@tutortrack.localhost"

BASELINE_FLAGS = [
    ("multi_branch", "Multiple branches per organisation (E02)", False),
    ("payroll", "Tutor payroll and payouts (E12)", False),
    ("pipeline", "Leads and sales pipeline (E17)", False),
    ("courses", "Group classes, courses and terms (E20)", False),
    ("ai_assistant", "AI assistant features (E31)", False),
]


@seed_step(order=0)
def platform_admin(ctx: SeedContext) -> None:
    from tutortrack.identity.models import User

    password = os.environ.get("SEED_ADMIN_PASSWORD", "tutortrack")
    admin = User.objects.filter(email=ADMIN_EMAIL).first()
    if admin is None:
        admin = User.objects.create_superuser(
            ADMIN_EMAIL, password, first_name="Platform", last_name="Admin"
        )
        ctx.log(f"    created {ADMIN_EMAIL} (password from SEED_ADMIN_PASSWORD)")
    ctx.admin = admin


@seed_step(order=10)
def demo_organisation(ctx: SeedContext) -> None:
    from tutortrack.tenancy.models import Organisation
    from tutortrack.tenancy.services import create_organisation

    org = Organisation.objects.filter(slug=DEMO_ORG_SLUG).first()
    if org is None:
        org = create_organisation(
            name="Bright Minds Tutoring",
            slug=DEMO_ORG_SLUG,
            owner=ctx.admin,
            country="GB",
            business_type=Organisation.BusinessType.AGENCY,
            status=Organisation.Status.ACTIVE,
        )
        ctx.log(f"    created organisation {org.name} -> {org.base_url}")
    ctx.organisation = org


@seed_step(order=20)
def feature_flags(ctx: SeedContext) -> None:
    for key, description, enabled in BASELINE_FLAGS:
        FeatureFlag.objects.get_or_create(
            key=key, defaults={"description": description, "enabled_globally": enabled}
        )
