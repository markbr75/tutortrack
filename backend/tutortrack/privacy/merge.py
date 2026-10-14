"""Privacy records follow a merged client, contact or student (FR-05-13): consent records
(the survivor's latest record per consent type still decides), data subject requests and
safeguarding concerns. Legal holds are not moved: a hold on either record blocks the
merge (checked by the merge engine)."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    GenericRef,
    MergeContext,
    MergeProvider,
    Move,
    count,
    generic_rows,
    moves,
    register,
    repoint,
    repoint_generic,
)

from .models import SafeguardingConcern

SUBJECTS = ("people.client", "people.contact", "people.student")
SAME = {s: (s,) for s in SUBJECTS}
CONSENTS = GenericRef("privacy.ConsentRecord", "subject_type", "subject_id", SAME)
REQUESTS = GenericRef("privacy.DataSubjectRequest", "subject_type", "subject_id", SAME)


def _count(ctx: MergeContext) -> list[Move]:
    concerns = (
        count(SafeguardingConcern, "student", ctx) if ctx.subject_type == "people.student" else 0
    )
    consents = generic_rows(CONSENTS, ctx.subject_type, ctx.source_id).count()
    requests = generic_rows(REQUESTS, ctx.subject_type, ctx.source_id).count()
    return moves(
        ("privacy.consents", _l("Consent records"), consents),
        ("privacy.requests", _l("Data subject requests"), requests),
        ("privacy.concerns", _l("Safeguarding concerns"), concerns),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    concerns = (
        repoint(SafeguardingConcern, "student", ctx) if ctx.subject_type == "people.student" else 0
    )
    return moves(
        ("privacy.consents", _l("Consent records"), repoint_generic(CONSENTS, ctx)),
        ("privacy.requests", _l("Data subject requests"), repoint_generic(REQUESTS, ctx)),
        ("privacy.concerns", _l("Safeguarding concerns"), concerns),
    )


register(
    MergeProvider(
        key="privacy",
        label="Privacy",
        subject_types=frozenset(SUBJECTS),
        count=_count,
        merge=_merge,
        generic=(CONSENTS, REQUESTS),
        order=100,
    )
)
