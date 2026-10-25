"""The workflow catalogue (E33-T02): plain questions, new record types, starts and actions.

* **Plain questions** are named checks about one kind of record ("the invoice is still
  unpaid"), used by "only if" and Yes / No splits instead of field conditions. Each reads
  the record's whitelisted context, so a dry run answers them the same way a run does.
* **Record types:** branch (schedules that run once per branch), invoice run and payment
  request. Packages came with gap G4.
* **Starts:** invoice run drafted and issued, payment requests, lesson report due, lesson
  unconfirmed, trial no-show and a family's first lesson. Date starts ("3 days before an
  invoice is due") are an event start plus a wait relative to a date on the record
  (``DATE_STARTS``); "statement due" is a monthly schedule on clients.
* **Actions** go through the owning app's services, are idempotent per run and step
  (``RunContext.key``) and declare the permission their author needs. When the service
  refuses because the record has moved on, the step is *skipped* with the reason.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.utils.translation import gettext as _
from django.utils.translation import gettext_noop as N_
from django.utils.translation import ngettext

from tutortrack.core.exceptions import BusinessRuleViolation, Conflict

from .actions import RunContext, _assignee, audit_money, skipped
from .builtins import CLIENT_FIELDS, _contacts, _d, _money, _subject_fields, _user, client_ctx
from .conditions import register_predicate
from .registry import Action, Subject, register_action, register_subject, register_trigger
from .registry import ActionField as A
from .registry import FieldDef as F

# --- record types --------------------------------------------------------------------------------


def branch_ctx(branch: Any) -> dict[str, Any]:
    return {"id": str(branch.pk), "name": branch.name, "timezone": branch.timezone}


def invoice_run_ctx(run: Any) -> dict[str, Any]:
    stats = run.stats or {}
    return {
        "id": str(run.pk),
        "status": run.status,
        "mode": run.mode,
        "period_start": _d(run.period_start),
        "period_end": _d(run.period_end),
        "review_until": _d(run.review_until),
        "drafts": int(stats.get("drafts") or 0),
        "branch": run.branch.name,
    }


def payment_request_ctx(request: Any) -> dict[str, Any]:
    return {
        "id": str(request.pk),
        "number": request.number,
        "status": request.status,
        "amount": _money(request.amount),
        "amount_paid": _money(request.amount_paid),
        "due_date": _d(request.due_date),
        "sent_at": _d(request.sent_at),
        "client": client_ctx(request.client),
    }


register_subject(
    Subject(
        key="branch", label="Branch", model="tenancy.Branch",
        fields=(F("branch.name", "Name"),), context=branch_ctx,
    )
)  # fmt: skip
register_subject(
    Subject(
        key="invoice_run", label="Invoice run", model="billing.InvoiceRun",
        fields=_subject_fields("invoice_run", (
            F("status", "Status", "choice",
              ("collecting", "review", "issuing", "completed", "failed")),
            F("mode", "Mode", "choice", ("arrears", "advance")),
            F("period_start", "Period start", "date"), F("period_end", "Period end", "date"),
            F("review_until", "Review ends", "datetime"), F("drafts", "Drafts", "number"),
            F("branch", "Branch"),
        )),
        context=invoice_run_ctx,
        recipients={"owner": lambda run: _user(run.requested_by)},
        owner=lambda run: run.requested_by,
        date_fields=("period_end", "review_until"),
    )
)  # fmt: skip
register_subject(
    Subject(
        key="payment_request", label="Payment request", model="billing.PaymentRequest",
        fields=_subject_fields("payment_request", (
            F("number", "Number"),
            F("status", "Status", "choice", ("open", "paid", "cancelled")),
            F("amount", "Amount", "number"), F("amount_paid", "Paid", "number"),
            F("due_date", "Due", "date"), F("sent_at", "Sent", "datetime"),
        ), ("client", CLIENT_FIELDS)),
        context=payment_request_ctx,
        recipients={"client": lambda r: _contacts(r.client)},
        owner=lambda r: r.client.account_manager.user if r.client.account_manager else None,
        date_fields=("due_date", "created_at"),
    )
)  # fmt: skip

# --- starts and stop-when events -----------------------------------------------------------------

for _event, _label, _subject in (
    ("invoice_run.drafted", "Invoice run drafted", "invoice_run"),
    ("invoice_run.issued", "Invoice run issued", "invoice_run"),
    ("invoice.sent", "Invoice emailed", "invoice"),
    ("invoice.partially_paid", "Invoice part paid", "invoice"),
    ("invoice.voided", "Invoice voided", "invoice"),
    ("invoice.written_off", "Invoice written off", "invoice"),
    ("payment_request.created", "Payment request created", "payment_request"),
    ("payment_request.sent", "Payment request sent", "payment_request"),
    ("payment_request.paid", "Payment request paid", "payment_request"),
    ("payment_request.cancelled", "Payment request cancelled", "payment_request"),
    ("lesson.unconfirmed", "Lesson not confirmed", "lesson"),
    ("lesson_report.due", "Lesson report due", "lesson_report"),
    ("lesson_report.escalated", "Lesson report escalated", "lesson_report"),
    ("trial_lesson.no_show", "Trial lesson missed", "enquiry"),
    ("client.first_lesson_completed", "A family's first lesson", "client"),
):
    register_trigger(_event, _label, _subject)

# "Before or after a date" starts: start on the event, then wait relative to the date.
DATE_STARTS = (
    {"key": "invoice.due_soon", "label": "Before or after an invoice is due",
     "subject": "invoice", "event": "invoice.issued", "date": "invoice.due_date"},
    {"key": "lesson.reminder_due", "label": "Before a lesson starts",
     "subject": "lesson", "event": "lesson.scheduled", "date": "lesson.start"},
    {"key": "package.expiring", "label": "Before a package expires",
     "subject": "package", "event": "package.activated", "date": "package.expires_at"},
)  # fmt: skip
# Schedule starts with a name: "statement due" is a monthly schedule on clients.
SCHEDULE_STARTS = (
    {"key": "statement.due", "label": "When monthly statements are due", "subject": "client",
     "config": {"frequency": "monthly", "day": 1, "time": "07:00", "start": "statement.due"}},
    {"key": "invoice_run.due", "label": "When invoicing is due (each branch)",
     "subject": "branch", "config": {"frequency": "monthly", "day": 1, "time": "06:00",
                                     "start": "invoice_run.due"}},
)  # fmt: skip


def statement_clients(on: date) -> list[str]:
    """Families with something on last month's statement (activity or a balance)."""
    from tutortrack.billing import statements

    start, end = statements.last_month(on)
    return sorted({client for client, _currency in statements.due(start, end)})


# The records a named schedule start picks, instead of every record of its type.
SCHEDULE_RECORDS = {"statement.due": statement_clients}
register_trigger("package.activated", "Package activated", "package")

# --- plain questions -----------------------------------------------------------------------------


def _root(ctx: dict[str, Any], key: str) -> dict[str, Any]:
    value = ctx.get(key)
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _unpaid(invoice: dict[str, Any]) -> bool:
    return invoice.get("status") in ("issued", "partially_paid") and (
        _number(invoice.get("balance_due")) > 0
    )


def _overdue(invoice: dict[str, Any]) -> bool:
    return _unpaid(invoice) and _number(invoice.get("days_overdue")) > 0


def _pays_automatically(ctx: dict[str, Any], key: str) -> bool:
    record = _root(ctx, key)
    client = record if key == "client" else _root(record, "client")
    return bool(client.get("auto_pay"))


QUESTIONS: tuple[tuple[str, str, str, Any], ...] = (
    ("invoice", "invoice.unpaid", "The invoice is still unpaid",
     lambda c: _unpaid(_root(c, "invoice"))),
    ("invoice", "invoice.overdue", "The invoice is overdue",
     lambda c: _overdue(_root(c, "invoice"))),
    ("invoice", "invoice.part_paid", "The invoice is part paid",
     lambda c: _root(c, "invoice").get("status") == "partially_paid"),
    ("invoice", "invoice.auto_pay", "The family pays automatically",
     lambda c: _pays_automatically(c, "invoice")),
    ("invoice_run", "invoice_run.in_review", "The run is waiting for review",
     lambda c: _root(c, "invoice_run").get("status") == "review"),
    ("invoice_run", "invoice_run.has_drafts", "The run has draft invoices",
     lambda c: _number(_root(c, "invoice_run").get("drafts")) > 0),
    ("payment_request", "payment_request.unpaid", "The payment request is still unpaid",
     lambda c: _root(c, "payment_request").get("status") == "open"),
    ("payment_request", "payment_request.auto_pay", "The family pays automatically",
     lambda c: _pays_automatically(c, "payment_request")),
    ("client", "client.auto_pay", "The family pays automatically",
     lambda c: _pays_automatically(c, "client")),
    ("client", "client.owes_money", "The family owes money",
     lambda c: _number(_root(c, "client").get("balance_due")) > 0),
    ("client", "client.active", "The family is active",
     lambda c: _root(c, "client").get("status") == "active"),
    ("student", "student.active", "The student is active",
     lambda c: _root(c, "student").get("status") == "active"),
    ("student", "student.on_trial", "The student is on a trial",
     lambda c: _root(c, "student").get("status") == "trial"),
    ("lesson", "lesson.first_for_student", "This is the student's first lesson",
     lambda c: bool(_root(c, "lesson").get("first_for_student"))),
    ("lesson", "lesson.still_planned", "The lesson is still going ahead",
     lambda c: _root(c, "lesson").get("status") == "planned"),
    ("lesson", "lesson.online", "The lesson is online",
     lambda c: bool(_root(c, "lesson").get("online"))),
    ("lesson", "lesson.trial", "This is a trial lesson",
     lambda c: bool(_root(c, "lesson").get("trial"))),
    ("lesson_report", "lesson_report.not_written", "The report still isn't written",
     lambda c: _root(c, "lesson_report").get("status") in ("pending", "draft", "returned")),
    ("lesson_report", "lesson_report.overdue", "The report is overdue",
     lambda c: bool(_root(c, "lesson_report").get("overdue"))),
    ("enquiry", "enquiry.open", "The enquiry is still open",
     lambda c: _root(c, "enquiry").get("status") == "open"),
    ("enquiry", "enquiry.has_owner", "Someone is looking after the enquiry",
     lambda c: bool(_root(c, "enquiry").get("owner"))),
    ("enquiry", "enquiry.trial_booked", "A trial lesson is booked",
     lambda c: bool(_root(c, "enquiry").get("trial_booked"))),
    ("enquiry", "enquiry.continuing", "The family wants to continue after the trial",
     lambda c: _root(c, "enquiry").get("trial_outcome") == "continuing"),
    ("package", "package.has_units_left", "The package has some left",
     lambda c: _number(_root(c, "package").get("units_remaining")) > 0),
    ("package", "package.auto_renew", "The package renews automatically",
     lambda c: bool(_root(c, "package").get("auto_renew"))),
    ("job", "job.active", "The job is active",
     lambda c: _root(c, "job").get("status") == "active"),
    ("tutor", "tutor.active", "The tutor is active",
     lambda c: _root(c, "tutor").get("status") == "active"),
    ("compliance_record", "compliance_record.verified", "The check is verified",
     lambda c: _root(c, "compliance_record").get("status") == "verified"),
    ("tutor_application", "tutor_application.open", "The application is still open",
     lambda c: _root(c, "tutor_application").get("status") == "open"),
)  # fmt: skip

for _subject, _key, _label, _fn in QUESTIONS:
    register_predicate(_key, _label, _fn, subject=_subject)


# --- billing actions -----------------------------------------------------------------------------

PERIODS = ("schedule", "last_week", "last_month", "this_week", "this_month", "next_month",
           "this_term")  # fmt: skip


def period_for(choice: str, today: date, ctx: RunContext) -> tuple[date, date]:
    """The dates an invoice run covers. "schedule" follows the workflow's schedule: weekly
    schedules invoice last week, others last month."""
    from tutortrack.billing.services import scheduled_period

    if choice == "schedule":
        frequency = (ctx.automation.trigger_config or {}).get("frequency")
        choice = "last_week" if frequency == "weekly" else "last_month"
    if choice in ("last_week", "last_month"):
        return scheduled_period("weekly" if choice == "last_week" else "monthly", today)
    if choice == "this_week":
        start = today - timedelta(days=today.weekday())
        return start, start + timedelta(days=6)
    first = today.replace(day=1)
    if choice == "next_month":
        first = (first + timedelta(days=32)).replace(day=1)
    if choice in ("this_month", "next_month"):
        return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    if choice == "this_term":
        from tutortrack.courses.models import Term

        term = Term.objects.filter(
            branch_id=_branch_id(ctx), start_date__lte=today, end_date__gte=today
        ).first()
        if term is None:
            raise BusinessRuleViolation(_("No term covers today."))
        return term.start_date, term.end_date
    raise BusinessRuleViolation(_("Choose the period to invoice."))


def _branch_id(ctx: RunContext) -> Any:
    return ctx.obj.pk if ctx.subject.key == "branch" else getattr(ctx.obj, "branch_id", None)


def start_invoice_run(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.billing import services as billing
    from tutortrack.tenancy.models import Branch

    start, end = period_for(str(config.get("period") or "schedule"), billing.org_today(), ctx)
    mode = "advance" if config.get("mode") == "advance" else "arrears"
    run, created = billing.create_run(
        period_start=start, period_end=end, mode=mode,
        branch=Branch.objects.get(pk=_branch_id(ctx)), user=ctx.author, **run_options(config),
    )  # fmt: skip
    return {"invoice_run": str(run.pk), "created": created, "period": [str(start), str(end)]}


def run_options(config: dict[str, Any]) -> dict[str, Any]:
    """The review window, issuing and emailing a workflow sets for its runs (E33 T04): the
    drafts wait ``review_days``, then are issued (``issue: after_review``) or wait for
    someone to approve them (``when_approved``); ``email`` sends each invoice when issued.
    Left out, the run follows the billing settings, as a run started by hand does."""
    out: dict[str, Any] = {}
    if config.get("review_days") not in (None, ""):
        out["review_days"] = max(0, min(int(config["review_days"]), 30))
    if config.get("issue") in ("after_review", "when_approved"):
        out["auto_issue"] = config["issue"] == "after_review"
    if config.get("email") is not None:
        out["send_invoices"] = bool(config["email"])
    return out


def describe_start_run(ctx: RunContext, config: dict[str, Any]) -> str:
    from tutortrack.billing.services import org_today

    start, end = period_for(str(config.get("period") or "schedule"), org_today(), ctx)
    text = _("Start an invoice run for %(start)s to %(end)s") % {"start": start, "end": end}
    options = run_options(config)
    if options.get("auto_issue") is False:
        text += _(", then wait for someone to approve the drafts")
    elif "review_days" in options:
        text += ngettext(
            ", review the drafts for %(n)s day, then issue them",
            ", review the drafts for %(n)s days, then issue them",
            options["review_days"],
        ) % {"n": options["review_days"]}
    if options.get("send_invoices"):
        text += _(" and email them")
    return text


def send_invoice_reminder(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """The payment reminder (worded for before, on or after the due date). Reminders after
    the due date also mark the invoice overdue, as the old dunning did."""
    from tutortrack.billing import services as billing

    invoice = ctx.obj
    if not invoice.is_open or not invoice.balance_due.is_positive():
        return skipped(_("invoice already paid"))
    offset = (billing.org_today() - invoice.due_date).days
    billing.send_reminder(invoice.pk, offset, dedupe_key=ctx.key)
    return {"reminded": str(invoice.pk), "days_from_due": offset}


def issue_invoice_run(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """Approve the run: its own workflow then issues the drafts (as "Approve run" does)."""
    from tutortrack.billing import services as billing

    if ctx.obj.status != "review":
        return skipped(_("the invoice run isn't waiting for review"))
    billing.approve_run(ctx.obj, user=ctx.author)
    audit_money(ctx, ctx.obj, "issue_invoice_run")
    return {"invoice_run": str(ctx.obj.pk)}


def email_invoice(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.billing import services as billing

    if ctx.obj.status in ("draft", "void"):
        return skipped(_("the invoice isn't issued"))
    if config.get("only_unpaid", True) and not ctx.obj.is_open:
        return skipped(_("invoice already paid"))
    return {"sent": billing.email_invoice(ctx.obj, key=ctx.key)}


def send_statement(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.billing import statements
    from tutortrack.billing.services import org_today

    start, end = statements.last_month(org_today())
    sent = statements.send([str(ctx.obj.pk)], start, end)
    return {"sent": sent} if sent else skipped(_("nothing to put on a statement"))


def collect_payment(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.payments import services as payments

    invoice = ctx.obj
    if not invoice.is_open or not invoice.balance_due.is_positive():
        return skipped(_("invoice already paid"))
    if payments.default_method(invoice.client) is None:
        return skipped(_("the family has no saved card or mandate"))
    try:
        payments.start_collection(invoice)
    except Conflict:
        return skipped(_("a payment is already being collected"))
    audit_money(ctx, invoice, "collect_payment")
    return {"collecting": str(invoice.pk)}


def open_collections(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.billing import dunning

    if not ctx.obj.is_open:
        return skipped(_("invoice already paid"))
    if not dunning.open_collections(ctx.obj.pk, dedupe_key=ctx.key):
        return skipped(_("collections are already open"))
    audit_money(ctx, ctx.obj, "open_collections")
    return {"collections": str(ctx.obj.pk)}


def remind_payment_request(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.billing import services as billing

    if not billing.remind_payment_request(ctx.obj.pk, dedupe_key=ctx.key):
        return skipped(_("the payment request isn't open"))
    return {"reminded": str(ctx.obj.pk)}


# --- lesson actions ------------------------------------------------------------------------------


def send_lesson_reminder(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """The lesson reminder message; each contact's reminder preferences still apply."""
    from tutortrack.comms import services as comms
    from tutortrack.comms.catalogue import load_lesson

    if ctx.obj.status != "planned":
        return skipped(_("the lesson isn't going ahead"))
    lesson = load_lesson(str(ctx.obj.pk))
    return {"sent": len(comms.notify("lesson_reminder", lesson, key=ctx.key))}


def report_overdue(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.delivery import services as delivery

    if not delivery.mark_report_overdue(ctx.obj.pk, dedupe_key=ctx.key):
        return skipped(_("the report is written or already overdue"))
    return {"overdue": str(ctx.obj.pk)}


def escalate_report(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.delivery import services as delivery

    if not delivery.escalate_report(ctx.obj.pk, dedupe_key=ctx.key):
        return skipped(_("the report is written or already escalated"))
    return {"escalated": str(ctx.obj.pk)}


# --- sales actions -------------------------------------------------------------------------------


def assign_owner(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.leads import services as leads

    user = _assignee(ctx, str(config.get("assignee") or ""))
    if user is None:
        return skipped(_("nobody to assign to"))
    if ctx.obj.owner_id != user.pk:
        leads.update_enquiry(ctx.obj, owner=user)
    return {"owner": str(user.pk)}


def ask_for_review(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    from tutortrack.growth import services as growth
    from tutortrack.growth.models import ReviewRequest

    client, tutor, student = _review_parties(ctx)
    if client is None:
        return skipped(_("this record has no family"))
    request = growth.request_review(
        client=client, tutor=tutor, student=student, trigger=ReviewRequest.Trigger.AUTOMATION
    )
    if request is None:
        return skipped(_("the family was already asked"))
    return {"review_request": str(request.pk)}


def _review_parties(ctx: RunContext) -> tuple[Any, Any, Any]:
    if ctx.subject.key == "lesson":
        attendee = ctx.obj.attendees.select_related("client", "student").first()
        link = ctx.obj.tutors.select_related("tutor").first()
        return (
            attendee.client if attendee else None,
            link.tutor if link else None,
            attendee.student if attendee else None,
        )
    if ctx.subject.key == "client":
        return ctx.obj, None, None
    return getattr(ctx.obj, "client", None), None, None


# --- general -------------------------------------------------------------------------------------


def start_workflow(ctx: RunContext, config: dict[str, Any]) -> dict[str, Any]:
    """Start another workflow for the same record (the loop limit applies)."""
    from . import services
    from .models import Automation

    target = Automation.objects.filter(pk=config.get("workflow")).first()
    if target is None or not target.enabled or target.paused:
        return skipped(_("the other workflow is off"))
    depth = (ctx.run.causation_depth + 1) if ctx.run is not None else 1
    run = services.prepare_run(
        target, subject_id=str(ctx.obj.pk), run_key=f"workflow:{ctx.key}", depth=depth
    )
    if run is None:
        return skipped(_("the other workflow didn't start for this record"))
    services.launch(run)
    return {"run": str(run.pk), "status": run.status}


def _describe(text: str) -> Any:
    return lambda ctx, config: _(text)


BILLING = ("invoice",)
for _action in (
    Action("start_invoice_run", "Start an invoice run", start_invoice_run, describe_start_run, (
        A("period", "Period", "choice", True, PERIODS),
        A("mode", "Invoice", "choice", False, ("arrears", "advance")),
        A("review_days", "Days to review the drafts", "number"),
        A("issue", "Then", "choice", False, ("after_review", "when_approved")),
        A("email", "Email each invoice when it is issued", "bool"),
    ), subjects=("branch",), permission="billing.invoice.create"),
    Action("issue_invoice_run", "Issue the invoice run", issue_invoice_run,
           _describe(N_("Issue the run's draft invoices")), (),
           subjects=("invoice_run",), permission="billing.invoice.issue"),
    Action("send_invoice_reminder", "Send a payment reminder", send_invoice_reminder,
           _describe(N_("Remind the family the invoice is due or overdue")), (),
           subjects=BILLING),
    Action("email_invoice", "Email the invoice", email_invoice,
           _describe(N_("Email the invoice with its PDF to the family")),
           (A("only_unpaid", "Only if still unpaid", "bool"),),
           subjects=BILLING, permission="billing.invoice.issue"),
    Action("send_statement", "Send a statement", send_statement,
           _describe(N_("Email last month's statement")), (),
           subjects=("client",), permission="billing.invoice.issue"),
    Action("collect_payment", "Collect payment now", collect_payment,
           _describe(N_("Charge the family's saved card or mandate")), (),
           subjects=BILLING, permission="payments.payment.record"),
    Action("open_collections", "Open a collections case", open_collections,
           _describe(N_("Open a collections case for the invoice")), (),
           subjects=BILLING, permission="billing.collections.manage"),
    Action("remind_payment_request", "Send payment request reminder", remind_payment_request,
           _describe(N_("Remind the family about the payment request")), (),
           subjects=("payment_request",), permission="billing.payment_request.manage"),
    Action("send_lesson_reminder", "Send lesson reminder", send_lesson_reminder,
           _describe(N_("Send the lesson reminder")), (), subjects=("lesson",)),
    Action("report_overdue", "Mark report overdue and notify", report_overdue,
           _describe(N_("Mark the report overdue and tell the tutor")), (),
           subjects=("lesson_report",), permission="delivery.report.approve"),
    Action("escalate_report", "Escalate to the tutor's manager", escalate_report,
           _describe(N_("Give the coordinators a task to chase the report")), (),
           subjects=("lesson_report",), permission="delivery.report.approve"),
    Action("assign_owner", "Assign to a person", assign_owner,
           _describe(N_("Assign the enquiry")),
           (A("assignee", "Assign to (owner, user:<id> or round_robin:<role>)", "text", True),),
           subjects=("enquiry",), permission="leads.enquiry.edit"),
    Action("ask_for_review", "Ask for a review", ask_for_review,
           _describe(N_("Ask the family for a review")), (),
           subjects=("client", "lesson", "enquiry", "invoice"),
           permission="growth.review.manage"),
    Action("start_workflow", "Start another workflow", start_workflow,
           _describe(N_("Start another workflow for this record")),
           (A("workflow", "Workflow", "workflow", True),)),
):  # fmt: skip
    register_action(_action)
