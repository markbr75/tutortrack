"""In-product sample data (FR-02-6): four enquiries spread over the pipeline: new, in later
open stages, and one lost (with a reason)."""

from __future__ import annotations

import contextlib

from django.utils.translation import gettext as _

from tutortrack.tenancy.demo import DemoContext, demo_provider

ENQUIRIES = [
    ("Leah", "Morgan", "Freddie", "Maths", "website"),
    ("Daniel", "Kowalski", "Zofia", "Chemistry", "referral"),
    ("Hannah", "Reid", "Isla", "English", "phone"),
    ("Omar", "Haddad", "Yusuf", "Physics", "website"),
]


@demo_provider(order=88)
def sample_enquiries(ctx: DemoContext) -> None:
    from tutortrack.core.exceptions import BusinessRuleViolation
    from tutortrack.tenancy.settings_service import get_setting

    from . import services
    from .models import Enquiry, PipelineStage

    pipeline = services.default_pipeline()
    open_stages = list(pipeline.stages.filter(kind=PipelineStage.Kind.OPEN).order_by("order"))
    sources = set(Enquiry.Source.values)
    enquiries = []
    for n, (first, last, child, subject, source) in enumerate(ENQUIRIES):
        enquiry = services.create_enquiry(
            contact={
                "first_name": first,
                "last_name": last,
                "email": f"{first.lower()}.{last.lower()}.sample@example.com",
            },
            students=[{"first_name": child}],
            subjects=[{"subject": subject}],
            source=source if source in sources else Enquiry.Source.MANUAL,
            notes=_("Sample enquiry."),
            pipeline=pipeline,
        )
        if 0 < n < 3 and len(open_stages) > n:
            enquiry = services.move(enquiry, open_stages[n])
        enquiries.append(enquiry)
    reasons = list(get_setting("leads.lost_reasons") or [])
    if reasons:
        with contextlib.suppress(BusinessRuleViolation):
            services.lose(enquiries[-1], reason=reasons[0], note=_("Sample lost enquiry."))
