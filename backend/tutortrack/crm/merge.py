"""CRM items follow a merged record (FR-05-13): notes, tasks, documents and tags move to
the survivor; a tag both records carry is kept once."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _l

from tutortrack.people.merging import (
    GenericRef,
    MergeContext,
    MergeProvider,
    Move,
    generic_rows,
    moves,
    register,
    repoint_generic,
)

from .models import TaggedItem

SUBJECTS = ("people.client", "people.contact", "people.student")
SAME = {s: (s,) for s in SUBJECTS}
NOTES = GenericRef("crm.Note", "target_type", "target_id", SAME)
TASKS = GenericRef("crm.Task", "target_type", "target_id", SAME)
DOCUMENTS = GenericRef("crm.Document", "target_type", "target_id", SAME)
TAGS = GenericRef("crm.TaggedItem", "target_type", "target_id", SAME)


def _count(ctx: MergeContext) -> list[Move]:
    def n(ref: GenericRef) -> int:
        return generic_rows(ref, ctx.subject_type, ctx.source_id).count()

    return moves(
        ("crm.notes", _l("Notes"), n(NOTES)),
        ("crm.tasks", _l("Tasks"), n(TASKS)),
        ("crm.documents", _l("Documents"), n(DOCUMENTS)),
        ("crm.tags", _l("Tags"), n(TAGS)),
    )


def _merge(ctx: MergeContext) -> list[Move]:
    kept = set(
        TaggedItem.objects.filter(
            target_type=ctx.subject_type, target_id=ctx.target_id
        ).values_list("tag_id", flat=True)
    )
    TaggedItem.objects.filter(
        target_type=ctx.subject_type, target_id=ctx.source_id, tag_id__in=kept
    ).delete()
    return moves(
        ("crm.notes", _l("Notes"), repoint_generic(NOTES, ctx)),
        ("crm.tasks", _l("Tasks"), repoint_generic(TASKS, ctx)),
        ("crm.documents", _l("Documents"), repoint_generic(DOCUMENTS, ctx)),
        ("crm.tags", _l("Tags"), repoint_generic(TAGS, ctx)),
    )


register(
    MergeProvider(
        key="crm",
        label="Notes, tasks, documents and tags",
        subject_types=frozenset(SUBJECTS),
        count=_count,
        merge=_merge,
        generic=(NOTES, TASKS, DOCUMENTS, TAGS),
    )
)
