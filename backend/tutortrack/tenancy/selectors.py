from __future__ import annotations

import uuid

from django.db.models import QuerySet

from tutortrack.core.context import tenant_context

from .models import Branch, Organisation


def default_branch_id(organisation_id: uuid.UUID) -> uuid.UUID:
    with tenant_context(organisation_id):
        return Branch.objects.filter(is_default=True).values_list("id", flat=True).get()


def branches(*, include_archived: bool = False) -> QuerySet[Branch]:
    """Branches of the organisation in context."""
    qs = Branch.objects.all()
    return qs if include_archived else qs.filter(archived_at__isnull=True)


def get_organisation(organisation_id: uuid.UUID) -> Organisation:
    return Organisation.objects.get(pk=organisation_id)
