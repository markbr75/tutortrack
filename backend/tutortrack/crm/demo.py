"""In-product sample data (FR-02-6): tags the sample families, students and tutors
"Sample data" so they are easy to tell apart from real records in lists and filters."""

from __future__ import annotations

from django.utils.translation import gettext as _

from tutortrack.tenancy.demo import DemoContext, demo_provider


@demo_provider(order=95)
def sample_tags(ctx: DemoContext) -> None:
    from . import services
    from .models import Tag

    tag, _created = Tag.objects.get_or_create(
        name=_("Sample data"), defaults={"colour": "#7c3aed", "entity_types": []}
    )
    for target_type, records in (
        ("people.client", ctx.extras.get("clients", {}).values()),
        ("people.student", ctx.extras.get("students", {}).values()),
        ("people.tutor", ctx.extras.get("tutors", {}).values()),
    ):
        ids = [str(r.pk) for r in records]
        if ids:
            services.apply_tag(tag, target_type, ids)
