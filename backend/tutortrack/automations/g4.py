"""Gap batch G4 for automations (FR-14-1, FR-14-3, FR-14-6).

* **Actions:** send the lesson feedback survey (E09), add to a mailing list (a tag that
  broadcast segments and the Mailchimp/Brevo sync use), send a WhatsApp message from an
  approved template, and send a message from a saved reply.
* **Package subject and triggers:** ``package.low``, ``package.depleted``,
  ``package.expiring`` and ``package.expired`` (E10 packages).
* **Recipe:** "Package under 2 hours: offer more" (the spec's "package < 2 hours").
"""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation

from .actions import CHANNELS, ROLES, RunContext, _client, recipients, render_text, send_message
from .builtins import CLIENT_FIELDS, _contacts, _d, _manager, _subject_fields, client_ctx
from .recipes import RECIPES, Recipe, _msg
from .registry import Action, Subject, register_action, register_subject, register_trigger
from .registry import ActionField as A
from .registry import FieldDef as F

# --- the package subject --------------------------------------------------------------------------


def package_ctx(purchase: Any) -> dict[str, Any]:
    return {
        "id": str(purchase.pk),
        "name": purchase.name,
        "quantity_type": purchase.quantity_type,
        "units_total": _d(purchase.units_total.normalize()),
        "units_used": _d(purchase.units_used.normalize()),
        "units_remaining": _d(purchase.units_remaining.normalize()),
        "status": purchase.status,
        "expires_at": _d(purchase.expires_at),
        "auto_renew": purchase.auto_renew,
        "client": client_ctx(purchase.client),
    }


register_subject(
    Subject(
        key="package",
        label="Package",
        model="billing.PackagePurchase",
        target="",
        fields=_subject_fields(
            "package",
            (
                F("name", "Name"),
                F("quantity_type", "Counted in", "choice", ("hours", "lessons", "credit")),
                F("units_total", "Units bought", "number"),
                F("units_remaining", "Units left", "number"),
                F(
                    "status",
                    "Status",
                    "choice",
                    ("pending", "active", "depleted", "expired", "cancelled"),
                ),
                F("expires_at", "Expires", "datetime"),
                F("auto_renew", "Renews automatically", "bool"),
            ),
            ("client", CLIENT_FIELDS),
        ),
        context=package_ctx,
        recipients={"client": lambda p: _contacts(p.client)},
        owner=lambda p: _manager(p.client),
        date_fields=("expires_at",),
    )
)
for _event, _label in (
    ("package.low", "Package running low"),
    ("package.depleted", "Package used up"),
    ("package.expiring", "Package about to expire"),
    ("package.expired", "Package expired"),
):
    register_trigger(_event, _label, "package")


# --- actions --------------------------------------------------------------------------------------


def feedback_survey(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """E09 lesson feedback: the family is asked to rate a completed lesson (the E09 rules
    apply: attended students only, once per student and lesson, opt-outs respected)."""
    from tutortrack.delivery import feedback

    sent = feedback.send_for_lesson(ctx.obj.pk)
    return {"sent": len(sent), "note": "" if sent else "nobody to ask (or feedback is off)"}


def mailing_list(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """Tag the client with the list's name (broadcast segments filter on tags) and push
    their contacts to the connected Mailchimp/Brevo audience, where the tag goes too. The
    sync only subscribes contacts with marketing consent."""
    from tutortrack.comms.marketing import queue_contact_sync
    from tutortrack.crm import services as crm

    name = str(config.get("list") or "").strip()
    if not name:
        raise BusinessRuleViolation(_("Name the list."))
    client = _client(ctx)
    tag = crm.get_or_create_tag(name)
    added = crm.apply_tag(tag, "people.client", [str(client.pk)])
    contacts = [str(pk) for pk in client.contacts.values_list("pk", flat=True)]
    if config.get("sync", True):
        for contact_id in contacts:
            queue_contact_sync(contact_id)
    return {"list": tag.name, "added": added, "contacts": len(contacts)}


def _whatsapp_template(config: dict[str, Any]) -> Any:
    from tutortrack.comms.models import WhatsAppTemplate

    template = WhatsAppTemplate.objects.filter(
        pk=config.get("template") or None, status=WhatsAppTemplate.Status.APPROVED
    ).first()
    if template is None:
        raise BusinessRuleViolation(_("Choose an approved WhatsApp template."))
    if template.category == WhatsAppTemplate.Category.MARKETING:
        raise BusinessRuleViolation(
            _("Marketing WhatsApp messages go out as broadcasts (they need consent).")
        )
    return template


def send_whatsapp(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """An approved (utility) WhatsApp template to people who opted in to WhatsApp."""
    from tutortrack.comms import senders
    from tutortrack.comms import services as comms
    from tutortrack.comms.catalogue import organisation

    template = _whatsapp_template(config)
    people = recipients(ctx, list(config.get("to") or []))
    sent = skipped = 0
    for person in people:
        allowed = comms.allowed_channels(person, "account")
        if not person.phone or allowed is None or "whatsapp" not in allowed:
            skipped += 1  # WhatsApp needs the person's opt-in
            continue
        context = {
            **ctx.context,
            "organisation": organisation(),
            "recipient": {"name": person.name, "first_name": person.first_name},
        }
        rendered = senders.render_whatsapp(template, context)
        message = comms.queue_message(
            type_key="automation_message",
            channel="whatsapp",
            recipient=person,
            subject="",
            body=rendered.body,
            dedupe_key=f"automation_whatsapp:{ctx.key}:{person.kind}:{person.id}",
            meta=rendered.meta,
            category="account",
        )
        sent += int(message is not None)
    return {"sent": sent, "skipped": skipped}


def describe_whatsapp(ctx: RunContext, config: dict[str, Any]) -> str:
    template = _whatsapp_template(config)
    people = recipients(ctx, list(config.get("to") or []))
    return _("Send the WhatsApp template %(t)s to %(n)s people (those who opted in)") % {
        "t": template.name,
        "n": len(people),
    }


def _saved_reply(config: dict[str, Any]) -> Any:
    from tutortrack.comms.models import CannedReply

    reply = CannedReply.objects.filter(pk=config.get("template") or None).first()
    if reply is None:
        raise BusinessRuleViolation(_("Choose a saved reply."))
    return reply


def send_saved(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """A saved reply (Settings → Messaging) as the message; its text may use the same
    variables as an inline message (``{{ recipient.first_name }}``, the record's fields)."""
    reply = _saved_reply(config)
    return send_message(
        ctx,
        {**config, "subject": config.get("subject") or reply.title, "body": reply.body},
    )


def describe_saved(ctx: RunContext, config: dict[str, Any]) -> str:
    reply = _saved_reply(config)
    people = recipients(ctx, list(config.get("to") or []))
    first = people[0] if people else None
    extra = {"recipient": {"name": first.name, "first_name": first.first_name}} if first else {}
    return _("Send the saved reply %(t)s to %(n)s people: %(body)s") % {
        "t": reply.title,
        "n": len(people),
        "body": render_text(reply.body, ctx, **extra)[:200],
    }


CLIENT_SUBJECTS = ("client", "student", "job", "invoice", "enquiry", "package")
for _action in (
    Action(
        "send_feedback_survey",
        "Send the lesson feedback survey",
        feedback_survey,
        lambda ctx, config: _("Ask the family to rate this lesson"),
        (),
        subjects=("lesson",),
    ),
    Action(
        "add_to_mailing_list",
        "Add to a mailing list (broadcasts, Mailchimp/Brevo)",
        mailing_list,
        lambda ctx, config: _("Add the client to the list %(l)s") % {"l": config.get("list")},
        (A("list", "List name", "text", True), A("sync", "Sync to Mailchimp/Brevo", "bool")),
        subjects=CLIENT_SUBJECTS,
    ),
    Action(
        "send_whatsapp",
        "Send a WhatsApp message",
        send_whatsapp,
        describe_whatsapp,
        (A("to", "To", "multi", True, ROLES), A("template", "Template", "whatsapp_template", True)),
    ),
    Action(
        "send_saved_reply",
        "Send a saved message",
        send_saved,
        describe_saved,
        (
            A("to", "To", "multi", True, ROLES),
            A("channels", "Channels", "multi", True, CHANNELS),
            A("template", "Saved message", "saved_reply", True),
            A("subject", "Subject (blank: the saved message's title)", "template"),
        ),
    ),
):
    register_action(_action)


# --- recipe ---------------------------------------------------------------------------------------

RECIPES.append(
    Recipe(
        "package_low_hours",
        "Package under 2 hours: offer more",
        "When an hours package has less than 2 hours left, email the family with a link to "
        "buy more. Packages count as running low at the units set in Settings → Billing "
        "(set it to 2 or more).",
        "event",
        {"event": "package.low"},
        [
            _msg(
                ["client"],
                ["email"],
                "{{ package.name }}: under 2 hours left",
                "Hello {{ recipient.first_name }},\n\n{{ package.name }} has "
                "{{ package.units_remaining }} hours left. Buy more in the client portal "
                "(Billing) so lessons carry on without a break.",
            )
        ],
        {
            "all": [
                {"field": "package.quantity_type", "op": "equals", "value": "hours"},
                {"field": "package.units_remaining", "op": "lt", "value": 2},
            ]
        },
    )
)
