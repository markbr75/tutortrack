"""Built-in actions (E14-T04, T07). Each ``run`` does its work through the owning app's
services and returns a small JSON result; ``describe`` says what it would do (dry run)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.utils.translation import gettext as _

from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.time import now

from .registry import Action, Subject, register_action
from .registry import ActionField as A

CHANNELS = ("email", "sms", "in_app")
ROLES = ("client", "tutor", "owner")


@dataclass
class RunContext:
    automation: Any
    subject: Subject
    obj: Any
    context: dict[str, Any]
    key: str  # unique per run and step: notifications and webhooks dedupe on it
    author: Any = None  # whose permissions finance actions use
    extra: dict[str, Any] = field(default_factory=dict)


def _fail(message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message)


def render_text(source: str, ctx: RunContext, **extra: Any) -> str:
    from tutortrack.comms import render
    from tutortrack.comms.catalogue import organisation

    if not source:
        return ""
    data = {**ctx.context, "organisation": organisation(), **extra}
    try:
        return render.render(source, data, timezone=str(data["organisation"].get("timezone", "")))
    except render.TemplateInvalid as exc:
        raise _fail(_("The message has an error: %(e)s") % {"e": exc}) from exc


def _amount(value: Any, field_name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _fail(_("%(f)s must be an amount.") % {"f": field_name}) from exc
    if amount <= 0:
        raise _fail(_("%(f)s must be more than zero.") % {"f": field_name})
    return amount


# --- messages -----------------------------------------------------------------------------------


def recipients(ctx: RunContext, roles: list[str]) -> list[Any]:
    from tutortrack.comms.catalogue import user_recipient
    from tutortrack.identity.models import User

    out: list[Any] = []
    for role in roles:
        if role == "owner":
            owner = ctx.subject.owner(ctx.obj) if ctx.subject.owner else None
            out += [user_recipient(owner)] if owner is not None else []
        elif role.startswith("user:"):
            user = User.objects.filter(pk=role.split(":", 1)[1]).first()
            out += [user_recipient(user)] if user is not None else []
        elif role in ctx.subject.recipients:
            out += ctx.subject.recipients[role](ctx.obj)
    seen, unique = set(), []
    for r in out:
        if (r.kind, r.id) not in seen:
            seen.add((r.kind, r.id))
            unique.append(r)
    return unique


def _message_payload(ctx: RunContext, config: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    people = recipients(ctx, list(config.get("to") or []))
    return people, {
        "recipients": people,
        "subject": str(config.get("subject") or ""),
        "body": str(config.get("body") or ""),
        "context": ctx.context,
    }


def send_message(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.comms import services as comms

    people, payload = _message_payload(ctx, config)
    if not people:
        return {"sent": 0, "note": "nobody to send to"}
    sent = 0
    for channel in [c for c in config.get("channels") or ["email"] if c in CHANNELS]:
        sent += len(comms.notify("automation_message", payload, key=ctx.key, only_channel=channel))
    return {"sent": sent, "recipients": len(people)}


def describe_message(ctx: RunContext, config: dict[str, Any]) -> str:
    people, _payload = _message_payload(ctx, config)
    first = people[0] if people else None
    extra = {"recipient": {"name": first.name, "first_name": first.first_name}} if first else {}
    subject = render_text(str(config.get("subject") or ""), ctx, **extra)
    body = render_text(str(config.get("body") or ""), ctx, **extra)
    return _("Send %(channels)s to %(n)s people: %(subject)s — %(body)s") % {
        "channels": "/".join(config.get("channels") or ["email"]),
        "n": len(people),
        "subject": subject,
        "body": body[:200],
    }


# --- tasks --------------------------------------------------------------------------------------


def _assignee(ctx: RunContext, rule: str) -> Any:
    from tutortrack.identity.models import Membership, User

    if rule == "owner":
        return ctx.subject.owner(ctx.obj) if ctx.subject.owner else None
    if rule.startswith("user:"):
        return User.objects.filter(pk=rule.split(":", 1)[1]).first()
    if rule.startswith("round_robin:"):
        from tutortrack.crm.selectors import open_task_counts

        role = rule.split(":", 1)[1]
        members = list(
            Membership.objects.filter(role=role, status=Membership.Status.ACTIVE)
            .select_related("user")
            .order_by("created_at")
        )
        if not members:
            return None
        counts = open_task_counts([m.user_id for m in members])
        return min(members, key=lambda m: counts.get(m.user_id, 0)).user
    return None


def create_task(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.crm import services as crm

    hours = int(config.get("due_in_hours") or 0)
    priority = str(config.get("priority") or "normal")
    task = crm.create_task(
        title=render_text(str(config.get("title") or ""), ctx)[:200] or _("Follow up"),
        description=render_text(str(config.get("description") or ""), ctx),
        target_type=ctx.subject.target,
        target_id=str(ctx.obj.pk) if ctx.subject.target else "",
        assignee=_assignee(ctx, str(config.get("assignee") or "")),
        due_at=now() + timedelta(hours=hours) if hours else None,
        priority=priority if priority in ("low", "normal", "high") else "normal",
    )
    return {"task": str(task.pk)}


def describe_task(ctx: RunContext, config: dict[str, Any]) -> str:
    who = _assignee(ctx, str(config.get("assignee") or ""))
    return _("Create task “%(title)s” for %(who)s") % {
        "title": render_text(str(config.get("title") or ""), ctx),
        "who": (who.get_full_name() or who.email) if who else _("nobody"),
    }


# --- fields, tags, stages -----------------------------------------------------------------------


def update_field(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    name = str(config.get("field") or "")
    setter = ctx.subject.setters.get(name)
    if setter is None:
        raise _fail(_("%(f)s can't be changed by automations.") % {"f": name})
    setter(ctx.obj, config.get("value"))
    return {"field": name, "value": config.get("value")}


def _tag(ctx: RunContext, config: dict[str, Any], remove: bool) -> dict[str, Any]:
    from tutortrack.crm import services as crm

    if not ctx.subject.target:
        raise _fail(_("This kind of record can't be tagged."))
    tag = crm.get_or_create_tag(str(config.get("tag") or "").strip())
    changed = crm.apply_tag(tag, ctx.subject.target, [str(ctx.obj.pk)], remove=remove)
    return {"tag": tag.name, "changed": changed}


def move_stage(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    name = str(config.get("stage") or "").strip().lower()
    if ctx.subject.key == "enquiry":
        from tutortrack.leads import services as leads
        from tutortrack.leads.models import PipelineStage

        stage = next(
            (s for s in PipelineStage.objects.filter(pipeline=ctx.obj.pipeline)
             if s.name.lower() == name),
            None,
        )  # fmt: skip
        if stage is None:
            raise _fail(_("No stage called %(s)s.") % {"s": config.get("stage")})
        if stage.pk != ctx.obj.stage_id:
            leads.move(ctx.obj, stage)
        return {"stage": stage.name}
    from tutortrack.recruitment import services as recruitment
    from tutortrack.recruitment.models import ApplicationStage

    app_stage = next((s for s in ApplicationStage.objects.all() if s.name.lower() == name), None)
    if app_stage is None:
        raise _fail(_("No stage called %(s)s.") % {"s": config.get("stage")})
    if app_stage.pk != ctx.obj.stage_id:
        recruitment.move(ctx.obj, app_stage)
    return {"stage": app_stage.name}


# --- webhooks -----------------------------------------------------------------------------------


def sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return mac.hexdigest()


def webhook_body(ctx: RunContext) -> bytes:
    return json.dumps(
        {
            "automation": str(ctx.automation.pk),
            "delivery": ctx.key,
            "subject": {"type": ctx.subject.key, "id": str(ctx.obj.pk)},
            "data": ctx.context,
        },
        sort_keys=True,
        default=str,
    ).encode()


def call_webhook(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """POST the context, signed ``X-TutorTrack-Signature: t=<unix>,v1=<hmac-sha256>`` over
    ``"<t>." + body`` with the automation's secret. Fetched through the SSRF guard."""
    from tutortrack.core.net import UnsafeURL, safe_urlopen

    body = webhook_body(ctx)
    stamp = int(time.time())
    signature = sign(ctx.automation.webhook_secret, stamp, body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "TutorTrack-Automations/1",
        "X-TutorTrack-Delivery": ctx.key,
        "X-TutorTrack-Signature": f"t={stamp},v1={signature}",
    }
    try:
        with safe_urlopen(
            str(config.get("url") or ""), data=body, headers=headers, method="POST", timeout=10
        ) as response:
            status = int(getattr(response, "status", 200))
    except UnsafeURL as exc:
        raise _fail(_("That address isn't allowed: %(e)s") % {"e": exc}) from exc
    except OSError as exc:
        raise _fail(_("The webhook failed: %(e)s") % {"e": exc}) from exc
    if status >= 400:
        raise _fail(_("The webhook answered %(s)s.") % {"s": status})
    return {"status": status}


# --- finance (permission-gated) -----------------------------------------------------------------


def _client(ctx: RunContext) -> Any:
    if ctx.subject.key == "client":
        return ctx.obj
    client = getattr(ctx.obj, "client", None)
    if client is None:
        raise _fail(_("This record has no client."))
    return client


def create_charge(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.billing import services as billing
    from tutortrack.core.money import Money

    client = _client(ctx)
    charge = billing.create_ad_hoc_charge(
        client=client,
        description=render_text(str(config.get("description") or ""), ctx) or _("Charge"),
        unit_price=Money(_amount(config.get("amount"), "Amount"), client.currency),
        student=ctx.obj if ctx.subject.key == "student" else None,
        job=ctx.obj if ctx.subject.key == "job" else None,
        user=ctx.author,
    )
    return {"charge": str(charge.pk)}


def late_fee(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.billing import services as billing
    from tutortrack.core.money import Money

    invoice = ctx.obj
    percent = Decimal(str(config.get("percent") or 0))
    minimum = Decimal(str(config.get("minimum") or 0))
    fee = max(invoice.balance_due.amount * percent / 100, minimum)
    fee = fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if fee <= 0 or invoice.balance_due.amount <= 0:
        return {"fee": "0", "note": "nothing owed"}
    charge = billing.create_ad_hoc_charge(
        client=invoice.client,
        description=_("Late payment fee for %(n)s") % {"n": invoice.number},
        unit_price=Money(fee, invoice.currency).round_to_minor(),
        category="late_fee",
        user=ctx.author,
    )
    return {"charge": str(charge.pk), "fee": str(fee)}


def payment_request(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.billing import services as billing
    from tutortrack.core.money import Money

    client = _client(ctx)
    days = int(config.get("due_in_days") or 0)
    request = billing.create_payment_request(
        client=client,
        amount=Money(_amount(config.get("amount"), "Amount"), client.currency),
        description=render_text(str(config.get("description") or ""), ctx),
        due_date=(now() + timedelta(days=days)).date() if days else None,
        user=ctx.author,
    )
    return {"payment_request": str(request.pk)}


def offer_job(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.matching import engine
    from tutortrack.matching import services as matching

    top = max(1, min(int(config.get("top") or 3), 10))
    matches = [
        m for m in engine.search(engine.criteria_for_job(ctx.obj), limit=top * 2)
        if not m.restricted
    ][:top]  # fmt: skip
    if not matches:
        return {"offered": 0, "note": "no matching tutors"}
    mode = "simultaneous" if config.get("mode") == "simultaneous" else "sequential"
    batch = matching.start_offers(ctx.obj, [m.tutor for m in matches], mode=mode)
    return {"offered": len(matches), "batch": str(batch.pk)}


def _describe(text: str) -> Any:
    def describe(ctx: RunContext, config: dict[str, Any]) -> str:
        values = {k: render_text(str(v), ctx) if isinstance(v, str) else v
                  for k, v in config.items()}  # fmt: skip
        return f"{text}: {values}" if values else text

    return describe


for _action in (
    Action("send_message", "Send a message", send_message, describe_message, (
        A("to", "To", "multi", True, ROLES), A("channels", "Channels", "multi", True, CHANNELS),
        A("subject", "Subject", "template"), A("body", "Message", "template", True),
    )),
    Action("create_task", "Create a task", create_task, describe_task, (
        A("title", "Title", "template", True), A("description", "Details", "template"),
        A("assignee", "Assign to (owner, user:<id> or round_robin:<role>)"),
        A("due_in_hours", "Due in (hours)", "number"),
        A("priority", "Priority", "choice", False, ("low", "normal", "high")),
    )),
    Action("update_field", "Change a field", update_field, _describe("Change a field"), (
        A("field", "Field", "text", True), A("value", "New value", "text", True),
    )),
    Action("add_tag", "Add a tag", lambda c, cfg: _tag(c, cfg, False), _describe("Add tag"),
           (A("tag", "Tag", "text", True),)),
    Action("remove_tag", "Remove a tag", lambda c, cfg: _tag(c, cfg, True),
           _describe("Remove tag"), (A("tag", "Tag", "text", True),)),
    Action("move_stage", "Move to a pipeline stage", move_stage, _describe("Move to stage"),
           (A("stage", "Stage", "text", True),), subjects=("enquiry", "tutor_application")),
    Action("webhook", "Call a webhook", call_webhook, _describe("POST to webhook"),
           (A("url", "URL (https)", "text", True),)),
    Action("create_charge", "Add a one-off charge", create_charge, _describe("Add a charge"), (
        A("description", "Description", "template", True), A("amount", "Amount", "number", True),
    ), subjects=("client", "student", "job", "invoice", "enquiry"),
        permission="billing.charge.create"),
    Action("late_fee", "Apply a late fee", late_fee, _describe("Apply a late fee"), (
        A("percent", "Percent of the balance", "number"), A("minimum", "Minimum fee", "number"),
    ), subjects=("invoice",), permission="billing.charge.create"),
    Action("payment_request", "Request a payment", payment_request,
           _describe("Request a payment"), (
        A("amount", "Amount", "number", True), A("description", "Description", "template"),
        A("due_in_days", "Due in (days)", "number"),
    ), subjects=("client", "student", "job", "enquiry"),
        permission="billing.payment_request.manage"),
    Action("offer_job", "Offer the job to the best tutors", offer_job,
           _describe("Offer the job to the top matches"), (
        A("top", "How many tutors", "number"),
        A("mode", "How", "choice", False, ("sequential", "simultaneous")),
    ), subjects=("job",), permission="matching.offer.manage"),
):  # fmt: skip
    register_action(_action)
