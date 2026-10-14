"""The platform "notify customers" tool (G6, FR-29-9): breach and incident notices to
organisations' owners and admins.

Platform staff pick a template (personal data breach, security incident, service
incident, legal change), fill in its details, preview it, choose the organisations (all
open ones, or a list) and send it with a reason. Each organisation's owners and admins are
emailed (and told in the app) through E13 comms, inside that organisation's tenant context,
and the notice is written to the organisation's own audit log, so customers can show
their regulator when and what they were told. The breach template follows
``docs/compliance/breach-notification.md`` (the 72-hour tenant notice).

Sending fans out one short Celery task per organisation; a re-run skips organisations that
already have a delivery (the comms dedupe key also stops double emails).
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.core import audit
from tutortrack.core.context import tenant_context
from tutortrack.core.db import PLATFORM_DB_ALIAS
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict
from tutortrack.core.time import now

from .models import CustomerNotice, CustomerNoticeDelivery

TEMPLATES: dict[str, dict[str, Any]] = {
    "breach": {
        "label": gettext_lazy("Personal data breach (72-hour notice)"),
        "kind": CustomerNotice.Kind.BREACH,
        "subject": "Important: a personal data incident affecting {organisation}",
        "body": (
            "We are writing to tell you about a personal data breach at TutorTrack that "
            "affects {organisation}.\n\n"
            "What happened: {summary}\n\n"
            "When: {when}\n\n"
            "Data involved: {data_affected}\n\n"
            "What we have done: {actions_taken}\n\n"
            "What you may need to do: {your_actions}\n\n"
            "As the controller of your clients' and tutors' data you may need to tell your "
            "regulator within 72 hours of becoming aware of it, and the people affected if "
            "there is a high risk to them. We will help with the information you need.\n\n"
            "Contact: {contact}"
        ),
        "variables": ["summary", "when", "data_affected", "actions_taken", "your_actions",
                      "contact"],
    },
    "security": {
        "label": gettext_lazy("Security incident (no personal data breach found)"),
        "kind": CustomerNotice.Kind.SECURITY,
        "subject": "Security notice for {organisation}",
        "body": (
            "We are investigating a security incident at TutorTrack.\n\n"
            "What happened: {summary}\n\nWhen: {when}\n\n"
            "What we have done: {actions_taken}\n\n"
            "We have found no evidence that your data was accessed. We will write again if "
            "that changes.\n\nContact: {contact}"
        ),
        "variables": ["summary", "when", "actions_taken", "contact"],
    },
    "service": {
        "label": gettext_lazy("Service incident"),
        "kind": CustomerNotice.Kind.SERVICE,
        "subject": "Service incident: {summary}",
        "body": (
            "TutorTrack had a service incident that affected {organisation}.\n\n"
            "What happened: {summary}\n\nWhen: {when}\n\n"
            "What we have done: {actions_taken}\n\nContact: {contact}"
        ),
        "variables": ["summary", "when", "actions_taken", "contact"],
    },
    "legal": {
        "label": gettext_lazy("Change to our terms, DPA or sub-processors"),
        "kind": CustomerNotice.Kind.LEGAL,
        "subject": "Changes to TutorTrack's terms for {organisation}",
        "body": "{summary}\n\nThe changes take effect on {when}.\n\nContact: {contact}",
        "variables": ["summary", "when", "contact"],
    },
}  # fmt: skip
MAX_TEXT = 20_000


class _Blank(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def templates() -> list[dict[str, Any]]:
    return [
        {
            "key": key,
            "title": str(t["label"]),
            "kind": str(t["kind"]),
            "subject": t["subject"],
            "body": t["body"],
            "variables": list(t["variables"]),
        }
        for key, t in TEMPLATES.items()
    ]


def render(text: str, variables: dict[str, Any], organisation_name: str) -> str:
    values = _Blank({k: str(v)[:4000] for k, v in variables.items()})
    values["organisation"] = organisation_name
    try:
        return text.format_map(values)
    except (ValueError, IndexError) as exc:
        raise BusinessRuleViolation(_("Use {name} placeholders only.")) from exc


def _organisations(ids: list[str]) -> list[Any]:
    from tutortrack.tenancy.models import Organisation

    qs = Organisation.objects.using(PLATFORM_DB_ALIAS).filter(closed_at__isnull=True)
    if ids:
        qs = qs.filter(pk__in=ids)
    return list(qs.order_by("name"))


@transaction.atomic
def create_notice(
    *,
    template: str,
    variables: dict[str, Any],
    organisation_ids: list[str],
    subject: str = "",
    body: str = "",
    user: Any = None,
) -> CustomerNotice:
    spec = TEMPLATES.get(template)
    if spec is None:
        raise BusinessRuleViolation(_("Choose a template."))
    notice = CustomerNotice.objects.create(
        kind=spec["kind"],
        template=template,
        subject=(subject or spec["subject"])[:300],
        body=(body or spec["body"])[:MAX_TEXT],
        variables={k: str(v)[:4000] for k, v in (variables or {}).items()},
        organisation_ids=[str(i) for i in organisation_ids or []],
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    render(notice.subject, notice.variables, "x")
    render(notice.body, notice.variables, "x")
    return notice


def preview(notice: CustomerNotice) -> dict[str, Any]:
    orgs = _organisations(notice.organisation_ids)
    sample = orgs[0].name if orgs else _("Example Tutoring")
    return {
        "subject": render(notice.subject, notice.variables, sample),
        "body": render(notice.body, notice.variables, sample),
        "organisations": len(orgs),
    }


@transaction.atomic
def send(notice: CustomerNotice, *, reason: str, user: Any = None) -> CustomerNotice:
    """Start sending (once). The fan-out runs after commit."""
    notice = CustomerNotice.objects.select_for_update().get(pk=notice.pk)
    if notice.status != CustomerNotice.Status.DRAFT:
        raise Conflict(_("This notice was already sent."))
    if not reason.strip():
        raise BusinessRuleViolation(
            _("Give a reason (e.g. the incident reference)."),
            extra={"errors": {"reason": [_("Required.")]}},
        )
    orgs = _organisations(notice.organisation_ids)
    notice.status = CustomerNotice.Status.SENDING
    notice.reason = reason.strip()[:500]
    notice.sent_by = user if getattr(user, "is_authenticated", False) else None
    notice.sent_at = now()
    notice.organisations_count = len(orgs)
    notice.save()
    ids = [str(o.pk) for o in orgs]
    notice_id = str(notice.pk)

    def fan_out() -> None:
        from .tasks import deliver_customer_notice

        for org_id in ids:
            deliver_customer_notice.apply_async(
                kwargs={"organisation_id": org_id, "notice_id": notice_id}
            )

    transaction.on_commit(fan_out)
    return notice


def recipients() -> list[Any]:
    """Active owners and admins of the organisation in context."""
    from tutortrack.comms.catalogue import user_recipient
    from tutortrack.identity.models import Membership

    rows = Membership.objects.filter(
        status=Membership.Status.ACTIVE,
        role__in=(Membership.Role.OWNER, Membership.Role.ADMIN),
        user__is_active=True,
    ).select_related("user")
    return [user_recipient(m.user) for m in rows]


def deliver(notice_id: str, organisation_id: str) -> int:
    """One organisation (in its tenant context): notify owners and admins, audit, record."""
    from tutortrack.comms import services as comms
    from tutortrack.tenancy.models import Organisation

    notice = CustomerNotice.objects.get(pk=notice_id)
    if CustomerNoticeDelivery.objects.filter(
        notice=notice, organisation_id=organisation_id
    ).exists():
        return 0
    with tenant_context(organisation_id), transaction.atomic():
        org = Organisation.objects.get(pk=organisation_id)
        subject = render(notice.subject, notice.variables, org.name)
        body = render(notice.body, notice.variables, org.name)
        messages = comms.notify(
            "platform_customer_notice",
            (subject, body, ""),
            key=f"customer-notice:{notice.pk}",
            immediate=True,
        )
        people = len({m.recipient_id for m in messages})
        audit.record(
            notice,
            "customer_notice",
            {"kind": [None, notice.kind], "subject": [None, subject], "recipients": [None, people]},
            object_repr=subject,
            organisation_id=org.pk,
        )
        CustomerNoticeDelivery.objects.create(
            notice=notice, organisation_id=org.pk, recipients=people, delivered_at=now()
        )
    _maybe_finish(notice.pk)
    return people


def _maybe_finish(notice_id: Any) -> None:
    with transaction.atomic():
        notice = CustomerNotice.objects.select_for_update().get(pk=notice_id)
        done = CustomerNoticeDelivery.objects.filter(notice=notice)
        if notice.status == CustomerNotice.Status.SENDING and done.count() >= (
            notice.organisations_count
        ):
            notice.status = CustomerNotice.Status.SENT
        notice.recipients_count = sum(done.values_list("recipients", flat=True))
        notice.save(update_fields=["status", "recipients_count"])
