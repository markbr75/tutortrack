"""Accounting links and a merged client (FR-05-13).

Contacts in the accounting system (Xero, QuickBooks...) are not merged from TutorTrack:
the ledger may hold invoices and payments against both. The merged client's contact link
is left as it is (documents already posted keep pointing at it; new documents use the
survivor's contact), and a staff note on the survivor says which contact to merge in the
ledger by hand. Invoice, payment and credit-note links are per document and need no
change."""

from __future__ import annotations

from html import escape

from django.utils.translation import gettext as _

from tutortrack.people.merging import MergeContext, MergeProvider, Move, register

from .models import ExternalRecordLink


def _links(ctx: MergeContext) -> list[ExternalRecordLink]:
    return list(
        ExternalRecordLink.objects.filter(object_type="contact", object_id=ctx.source_id)
        .exclude(external_id="")
        .select_related("connection")
    )


def _describe(link: ExternalRecordLink) -> str:
    name = link.label or link.external_number or link.external_id
    return f"{link.provider}: {name}"


def _notes(ctx: MergeContext) -> list[str]:
    links = _links(ctx)
    if not links:
        return []
    return [
        _(
            "The merged client has its own contact in your accounting system (%(contacts)s). "
            "Contacts there aren't merged automatically: a note will remind you to merge them "
            "by hand."
        )
        % {"contacts": ", ".join(_describe(link) for link in links)}
    ]


def _count(ctx: MergeContext) -> list[Move]:
    return []


def _merge(ctx: MergeContext) -> list[Move]:
    links = _links(ctx)
    if not links:
        return []
    from tutortrack.crm import services as crm

    body = _(
        "%(source)s was merged into this client. Its accounting contact (%(contacts)s) was "
        "not merged: merge it with this client's contact in your accounting system by hand."
    ) % {
        "source": escape(str(ctx.source)),
        "contacts": escape(", ".join(_describe(link) for link in links)),
    }
    crm.create_note(target_type="people.client", target_id=ctx.target_id, body=f"<p>{body}</p>")
    ctx.note(_("A note on the client reminds you to merge the accounting contacts."))
    return []


register(
    MergeProvider(
        key="accounting",
        label="Accounting",
        subject_types=frozenset({"people.client"}),
        count=_count,
        merge=_merge,
        notes=_notes,
        order=150,
    )
)
