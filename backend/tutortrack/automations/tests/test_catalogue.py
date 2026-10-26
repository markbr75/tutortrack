"""E33 T02: the workflow catalogue: plain questions, record types, starts and actions."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction

from tutortrack.automations import conditions, registry, services
from tutortrack.automations.actions import RunContext
from tutortrack.automations.models import Automation
from tutortrack.billing import services as billing
from tutortrack.billing.models import CollectionsCase, InvoiceRun
from tutortrack.billing.tests.test_billing import (
    complete,
    events_of,
    gbp,
    issued_invoice,
    lesson,
    local_today,
    set_settings,
)
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import AuditEntry
from tutortrack.core.money import Money
from tutortrack.core.time import now
from tutortrack.delivery.models import LessonReport
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.leads import services as leads
from tutortrack.people.tests.factories import TutorProfileFactory
from tutortrack.scheduling import services as scheduling
from tutortrack.tenancy.models import Branch

pytestmark = pytest.mark.django_db

# Each plain question with a record context where it is true and one where it is false.
CASES = {
    "invoice.unpaid": ({"invoice": {"status": "issued", "balance_due": "10"}},
                       {"invoice": {"status": "paid", "balance_due": "0"}}),
    "invoice.overdue": ({"invoice": {"status": "issued", "balance_due": "10", "days_overdue": 3}},
                        {"invoice": {"status": "issued", "balance_due": "10", "days_overdue": 0}}),
    "invoice.part_paid": ({"invoice": {"status": "partially_paid"}},
                          {"invoice": {"status": "issued"}}),
    "invoice.auto_pay": ({"invoice": {"client": {"auto_pay": True}}},
                         {"invoice": {"client": {"auto_pay": False}}}),
    "invoice_run.in_review": ({"invoice_run": {"status": "review"}},
                              {"invoice_run": {"status": "completed"}}),
    "invoice_run.has_drafts": ({"invoice_run": {"drafts": 4}}, {"invoice_run": {"drafts": 0}}),
    "payment_request.unpaid": ({"payment_request": {"status": "open"}},
                               {"payment_request": {"status": "cancelled"}}),
    "payment_request.auto_pay": ({"payment_request": {"client": {"auto_pay": True}}},
                                 {"payment_request": {"client": {}}}),
    "client.auto_pay": ({"client": {"auto_pay": True}}, {"client": {"auto_pay": False}}),
    "client.owes_money": ({"client": {"balance_due": "12.50"}}, {"client": {"balance_due": "0"}}),
    "client.active": ({"client": {"status": "active"}}, {"client": {"status": "dormant"}}),
    "student.active": ({"student": {"status": "active"}}, {"student": {"status": "paused"}}),
    "student.on_trial": ({"student": {"status": "trial"}}, {"student": {"status": "active"}}),
    "lesson.first_for_student": ({"lesson": {"first_for_student": True}},
                                 {"lesson": {"first_for_student": False}}),
    "lesson.still_planned": ({"lesson": {"status": "planned"}},
                             {"lesson": {"status": "cancelled"}}),
    "lesson.online": ({"lesson": {"online": True}}, {"lesson": {"online": False}}),
    "lesson.trial": ({"lesson": {"trial": True}}, {"lesson": {}}),
    "lesson_report.not_written": ({"lesson_report": {"status": "draft"}},
                                  {"lesson_report": {"status": "submitted"}}),
    "lesson_report.overdue": ({"lesson_report": {"overdue": True}},
                              {"lesson_report": {"overdue": False}}),
    "enquiry.open": ({"enquiry": {"status": "open"}}, {"enquiry": {"status": "won"}}),
    "enquiry.has_owner": ({"enquiry": {"owner": "Sam"}}, {"enquiry": {"owner": ""}}),
    "enquiry.trial_booked": ({"enquiry": {"trial_booked": True}},
                             {"enquiry": {"trial_booked": False}}),
    "enquiry.continuing": ({"enquiry": {"trial_outcome": "continuing"}},
                           {"enquiry": {"trial_outcome": "undecided"}}),
    "enquiry.not_imported": ({"enquiry": {"source": "form"}}, {"enquiry": {"source": "import"}}),
    "enquiry.stage_has_time_limit": ({"enquiry": {"stage_deadline": "2026-11-01T09:00:00+00:00"}},
                                     {"enquiry": {"stage_deadline": None}}),
    "package.active": ({"package": {"status": "active"}}, {"package": {"status": "expired"}}),
    "package.has_units_left": ({"package": {"units_remaining": "1.5"}},
                               {"package": {"units_remaining": "0"}}),
    "package.auto_renew": ({"package": {"auto_renew": True}}, {"package": {"auto_renew": False}}),
    "job.active": ({"job": {"status": "active"}}, {"job": {"status": "paused"}}),
    "tutor.active": ({"tutor": {"status": "active"}}, {"tutor": {"status": "inactive"}}),
    "compliance_record.verified": ({"compliance_record": {"status": "verified"}},
                                   {"compliance_record": {"status": "expired"}}),
    "tutor_application.open": ({"tutor_application": {"status": "open"}},
                               {"tutor_application": {"status": "hired"}}),
    "review_request.open": ({"review_request": {"status": "reminded"}},
                            {"review_request": {"status": "submitted"}}),
}  # fmt: skip


@pytest.mark.parametrize("key", sorted(CASES))
def test_each_plain_question_answers_yes_and_no(key):
    yes, no = CASES[key]
    assert conditions.evaluate({"predicate": key}, yes) is True
    assert conditions.evaluate({"predicate": key}, no) is False
    assert conditions.evaluate({"predicate": key}, {}) is False  # a missing record is a no


def test_every_question_is_tested_and_about_a_known_record_type():
    questions = conditions.questions()
    assert {q["key"] for q in questions} == set(CASES)
    for q in questions:
        assert registry.subject(q["subject"]) is not None, q
        assert q["key"].split(".")[0] == q["subject"]


def _check(org, event, step, **fields):
    with tenant_context(org):
        return services.validate_definition(
            trigger_type="event", trigger_config={"event": event}, conditions_={},
            steps=[step], **fields,
        )  # fmt: skip


def test_questions_and_new_actions_are_checked_against_the_record_type(org):
    tag = {"type": "action", "action": "add_tag", "config": {"tag": "x"}}
    assert _check(org, "invoice.issued", {**tag, "only_if": {"predicate": "invoice.unpaid"}})
    with pytest.raises(BusinessRuleViolation) as caught:
        _check(org, "student.created", {**tag, "only_if": {"predicate": "invoice.unpaid"}})
    assert "another kind of record" in caught.value.extra["errors"]["steps"][0]
    # Yes / No splits use the same list.
    split = {"type": "branch", "if": {"predicate": "student.active"}, "then": [tag]}
    assert _check(org, "student.created", split)
    with pytest.raises(BusinessRuleViolation):
        _check(org, "student.created", {**split, "if": {"predicate": "lesson.online"}})
    # Billing actions only work on their record type; "start another workflow" needs one
    # about the same kind of record.
    issue = {"type": "action", "action": "issue_invoice_run", "config": {}}
    assert _check(org, "invoice_run.drafted", issue)
    with pytest.raises(BusinessRuleViolation):
        _check(org, "invoice.issued", issue)
    with tenant_context(org), transaction.atomic():
        other = services.create_automation(
            name="Other", trigger_type="manual", trigger_config={"subject": "invoice"},
            steps=[tag],
        )  # fmt: skip
    chain = {"type": "action", "action": "start_workflow", "config": {"workflow": str(other.pk)}}
    assert _check(org, "invoice.issued", chain)
    with pytest.raises(BusinessRuleViolation):
        _check(org, "student.created", chain)


def test_new_actions_need_their_permission(org):
    tutor = MembershipFactory(organisation=org, role="tutor").user
    step = {"type": "action", "action": "collect_payment", "config": {}}
    from tutortrack.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        _check(org, "invoice.issued", step, user=tutor)


# --- running the actions --------------------------------------------------------------------------


def act(org, key, subject_key, obj, config=None, *, step="0"):
    """Run one action the way ``execute_step`` does (for an automation saved for audit)."""
    with tenant_context(org), transaction.atomic():
        automation, _ = Automation.objects.get_or_create(
            name=f"Test {subject_key}", defaults={
                "trigger_type": "manual", "subject_type": subject_key,
                "trigger_config": {"subject": subject_key},
            },
        )  # fmt: skip
        subject = registry.subject(subject_key)
        obj = type(obj).objects.get(pk=obj.pk)
        ctx = RunContext(
            automation=automation, subject=subject, obj=obj,
            context=services.build_context(subject, obj), key=f"test:{automation.pk}:{step}",
        )  # fmt: skip
        return registry.action(key).run(ctx, config or {})


def audited(org, obj, action):
    with tenant_context(org):
        entry = AuditEntry.objects.filter(object_id=str(obj.pk), action=action).get()
    assert entry.changes["version"] == [None, 1]
    return entry


def test_invoice_runs_are_drafted_issued_and_started_by_workflows(org, family):
    complete(org, lesson(org, family))
    today = local_today(org)
    with tenant_context(org):
        run, _ = billing.create_run(
            period_start=today - timedelta(days=7), period_end=today, start_workflow=False
        )
        billing.collect_run(run.pk)
    [drafted] = events_of(org, "invoice_run.drafted")
    assert drafted["drafts"] == 1
    with tenant_context(org):
        run.refresh_from_db()
        context = services.build_context(registry.subject("invoice_run"), run)
    assert context["invoice_run"]["status"] == "review"
    assert conditions.evaluate({"predicate": "invoice_run.has_drafts"}, context)
    # "Issue the invoice run" approves it, as staff would; the run's workflow issues.
    assert act(org, "issue_invoice_run", "invoice_run", run) == {"invoice_run": str(run.pk)}
    audited(org, run, "workflow.issue_invoice_run")
    with tenant_context(org):
        run.refresh_from_db()
        assert run.approved_at is not None
        billing.issue_run(run.pk)
    assert events_of(org, "invoice_run.issued")[0]["issued"] == 1
    assert act(org, "issue_invoice_run", "invoice_run", run) == {
        "skipped": "the invoice run isn't waiting for review"
    }
    # "Start an invoice run" for a branch: last month, idempotent per period.
    with tenant_context(org):
        branch = Branch.objects.get(is_default=True)
    first = act(org, "start_invoice_run", "branch", branch, {"period": "last_month"},
                step="a")  # fmt: skip
    again = act(org, "start_invoice_run", "branch", branch, {"period": "last_month"},
                step="b")  # fmt: skip
    assert first["invoice_run"] == again["invoice_run"]
    assert again["created"] is False
    with tenant_context(org):
        made = InvoiceRun.objects.get(pk=first["invoice_run"])
    assert made.period_end == today.replace(day=1) - timedelta(days=1)


def test_money_steps_are_skipped_once_the_invoice_is_paid(org, family):
    invoice = issued_invoice(org, family)
    result = act(org, "email_invoice", "invoice", invoice)
    assert "sent" in result
    assert act(org, "collect_payment", "invoice", invoice) == {
        "skipped": "the family has no saved card or mandate"
    }
    assert act(org, "open_collections", "invoice", invoice, step="1") == {
        "collections": str(invoice.pk)
    }
    audited(org, invoice, "workflow.open_collections")
    with tenant_context(org):
        assert CollectionsCase.objects.filter(invoice=invoice, status="open").count() == 1
    assert "skipped" in act(org, "open_collections", "invoice", invoice, step="2")
    with tenant_context(org):
        billing.allocate_payment(invoice, invoice.balance_due)
    paid = {"skipped": "invoice already paid"}
    assert act(org, "late_fee", "invoice", invoice, {"percent": "5"}) == paid
    assert act(org, "collect_payment", "invoice", invoice) == paid
    assert act(org, "email_invoice", "invoice", invoice) == paid
    assert act(org, "email_invoice", "invoice", invoice, {"only_unpaid": False}, step="3") != paid


def test_payment_request_reminders_and_statements(org, family):
    with tenant_context(org), transaction.atomic():
        request = billing.create_payment_request(
            client=family["client"], amount=Money(Decimal("50"), "GBP"), description="Term"
        )
    with tenant_context(org):
        context = services.build_context(registry.subject("payment_request"), request)
    assert conditions.evaluate({"predicate": "payment_request.unpaid"}, context)
    assert act(org, "remind_payment_request", "payment_request", request) == {
        "reminded": str(request.pk)
    }
    assert len(events_of(org, "payment_request.sent")) == 1
    with tenant_context(org), transaction.atomic():
        billing.cancel_payment_request(request)
    assert "skipped" in act(org, "remind_payment_request", "payment_request", request, step="1")
    # A family with nothing on last month's ledger gets no statement.
    assert "skipped" in act(org, "send_statement", "client", family["client"])


def test_lesson_and_report_actions(org, family):
    set_settings(org, "delivery", {"delivery.report_required": True})
    upcoming = lesson(org, family, hours_ago=-48)
    assert "sent" in act(org, "send_lesson_reminder", "lesson", upcoming)
    done = lesson(org, family, hours_ago=5)
    complete(org, done)
    with tenant_context(org):
        report = LessonReport.objects.get(lesson=done)
    assert act(org, "report_overdue", "lesson_report", report) == {"overdue": str(report.pk)}
    assert act(org, "escalate_report", "lesson_report", report) == {"escalated": str(report.pk)}
    with tenant_context(org):
        report.refresh_from_db()
        assert report.overdue_at is not None
        assert report.escalated_at is not None
    assert "skipped" in act(org, "escalate_report", "lesson_report", report, step="1")
    with tenant_context(org), transaction.atomic():
        scheduling.cancel_lesson(upcoming, reason="Ill", chargeable=False)
    assert act(org, "send_lesson_reminder", "lesson", upcoming, step="1") == {
        "skipped": "the lesson isn't going ahead"
    }


def test_sales_actions_assign_and_ask_for_a_review(org, family):
    with tenant_context(org):
        enquiry = leads.create_enquiry(
            contact={"first_name": "Priya", "last_name": "Patel", "email": "p@example.com"},
            students=[{"first_name": "Arjun"}],
        )
    owner = MembershipFactory(organisation=org, role="admin").user
    result = act(org, "assign_owner", "enquiry", enquiry, {"assignee": f"user:{owner.pk}"})
    assert result == {"owner": str(owner.pk)}
    with tenant_context(org):
        enquiry.refresh_from_db()
        assert enquiry.owner_id == owner.pk
    assert "review_request" in act(org, "ask_for_review", "client", family["client"])
    assert act(org, "ask_for_review", "client", family["client"], step="1") == {
        "skipped": "the family was already asked"
    }


# --- new starts -------------------------------------------------------------------------------


def test_trial_no_show_and_a_familys_first_lesson_are_published(org, family):
    first = lesson(org, family, hours_ago=8)
    second = lesson(org, family, hours_ago=4)
    complete(org, first)
    complete(org, second)
    with tenant_context(org), transaction.atomic():
        scheduling.note_first_lessons(type(first).objects.get(pk=first.pk))
        scheduling.note_first_lessons(type(second).objects.get(pk=second.pk))
        scheduling.note_first_lessons(type(first).objects.get(pk=first.pk))  # once only
    assert events_of(org, "client.first_lesson_completed") == [{"lesson_id": str(first.pk)}]

    with tenant_context(org):
        enquiry = leads.create_enquiry(
            contact={"first_name": "Sam", "last_name": "Lee", "email": "s@example.com"},
            students=[{"first_name": "Kai"}],
        )
        start = (now() + timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
        enquiry = leads.book_trial(
            enquiry, start=start, end=start + timedelta(hours=1), service=family["service"],
            tutor=TutorProfileFactory(organisation=org, status="active"), price=gbp("0"),
        )  # fmt: skip
    with tenant_context(org):
        assert leads.note_trial_no_show(enquiry.trial_lesson_id) is True
        assert leads.note_trial_no_show(first.pk) is False  # not a trial lesson
    assert events_of(org, "trial_lesson.no_show") == [{"lesson_id": str(enquiry.trial_lesson_id)}]


# --- API --------------------------------------------------------------------------------------


def test_workflow_schema_lists_what_the_editor_offers(api):
    body = api.get("/api/v1/workflow-schema").json()
    kinds = {r["key"]: r for r in body["record_types"]}
    assert {"invoice_run", "payment_request", "branch", "invoice"} <= set(kinds)
    assert {"path": "invoice.due_date", "label": "Due", "type": "date"} in kinds["invoice"][
        "date_fields"
    ]
    assert "invoice.paid" in kinds["invoice"]["stop_when"]
    assert "invoice_run.drafted" in {e["event"] for e in body["starts"]["events"]}
    assert {d["key"] for d in body["starts"]["dates"]} == {
        "invoice.due_soon", "lesson.reminder_due", "package.expiring",
    }  # fmt: skip
    assert {"key": "invoice.unpaid", "label": "The invoice is still unpaid",
            "subject": "invoice"} in body["questions"]  # fmt: skip
    issue = next(a for a in body["actions"] if a["key"] == "issue_invoice_run")
    assert issue["subjects"] == ["invoice_run"]
    assert issue["permission"] == "billing.invoice.issue"


def test_pause_and_resume_through_the_api(org, api):
    with tenant_context(org), transaction.atomic():
        rule = services.create_automation(
            name="Chase", trigger_type="event", trigger_config={"event": "invoice.issued"},
            steps=[{"type": "action", "action": "add_tag", "config": {"tag": "x"}}],
        )  # fmt: skip
    paused = api.post(f"/api/v1/automations/{rule.pk}/pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True
    assert api.post(f"/api/v1/automations/{rule.pk}/resume").json()["paused"] is False
    with tenant_context(org):
        rule.refresh_from_db()
        assert rule.version == 1  # pausing isn't a new version
        assert AuditEntry.objects.filter(object_id=str(rule.pk), action="pause").exists()


def test_every_start_and_stop_when_event_reaches_the_engine():
    """Triggers registered by the catalogue (and g4) are subscribed too, not only E14's."""
    from tutortrack.core.events.registry import subscribers_for

    missing = [
        t.event for t in registry.triggers()
        if "automations.on_event" not in {s.name for s in subscribers_for(t.event)}
    ]  # fmt: skip
    assert missing == []
