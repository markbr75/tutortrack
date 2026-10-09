"""E09-T01..T08: completion and attendance, cancellation policies, makeup credits, report
templates, reports, SLA steps and the unconfirmed queue."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tutortrack.catalogue.tests.factories import ServiceFactory
from tutortrack.core.context import tenant_context
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import AuditEntry, OutboxEvent
from tutortrack.core.money import Money
from tutortrack.core.testing import TenantIsolationTestMixin, client_for
from tutortrack.core.time import now
from tutortrack.crm.models import Task
from tutortrack.delivery import balance, policies, selectors, services, templates
from tutortrack.delivery.models import (
    CancellationPolicy,
    CancellationRecord,
    LessonReport,
    MakeupCredit,
    ReportTemplate,
)
from tutortrack.identity.tests.factories import MembershipFactory
from tutortrack.people.tests.factories import ClientFactory, StudentFactory, TutorProfileFactory
from tutortrack.scheduling import services as scheduling
from tutortrack.scheduling.models import Lesson
from tutortrack.tenancy import settings_service

pytestmark = pytest.mark.django_db


@pytest.fixture
def people(org):
    client = ClientFactory(organisation=org, display_name="The Patels")
    student = StudentFactory(organisation=org, client=client, first_name="Arjun", last_name="Patel")
    membership = MembershipFactory(organisation=org, role="tutor")
    tutor = TutorProfileFactory(
        organisation=org, status="active", first_name="Nia", last_name="Adeyemi",
        membership=membership,
    )  # fmt: skip
    service = ServiceFactory(organisation=org, name="Maths 1:1")
    return {
        "client": client,
        "student": student,
        "tutor": tutor,
        "tutor_user": membership.user,
        "service": service,
    }


@pytest.fixture
def staff(org):
    return client_for(org, MembershipFactory(organisation=org, role="admin").user)


@pytest.fixture
def tutor_api(org, people):
    return client_for(org, people["tutor_user"])


def snap(moment):
    """Lesson times use 5-minute steps."""
    return moment.replace(second=0, microsecond=0, minute=moment.minute - moment.minute % 5)


def lesson_at(org, people, start, minutes=60, **kwargs):
    start = snap(start)
    with tenant_context(org):
        return scheduling.create_lesson(
            start=start,
            end=start + timedelta(minutes=minutes),
            service=kwargs.pop("service", people["service"]),
            attendees=kwargs.pop("attendees", [{"student": people["student"]}]),
            tutors=kwargs.pop("tutors", [{"tutor": people["tutor"]}]),
            timezone="Europe/London",
            override_conflicts=True,
            **kwargs,
        ).lesson


def past(org, people, hours=2, **kwargs):
    return lesson_at(org, people, now().replace(microsecond=0) - timedelta(hours=hours), **kwargs)


def future(org, people, hours=48, **kwargs):
    return lesson_at(org, people, now().replace(microsecond=0) + timedelta(hours=hours), **kwargs)


def events_of(org, kind):
    with tenant_context(org):
        return [
            e.payload["data"]
            for e in OutboxEvent.objects.filter(event_type=kind).order_by("occurred_at")
        ]


def set_settings(org, area, values):
    with tenant_context(org):
        settings_service.update_settings(area, values)


# --- completion and attendance (T01) ------------------------------------------------------------


def test_complete_with_attendance_applies_policy_and_requests_report(org, tutor_api, people):
    second = StudentFactory(organisation=org, client=people["client"], first_name="Maya")
    group = ServiceFactory(
        organisation=org, name="Maths group", format="small_group", max_students=6
    )
    lesson = past(
        org,
        people,
        service=group,
        attendees=[{"student": people["student"]}, {"student": second}],
    )
    with tenant_context(org):
        attendees = {a.student_id: a for a in lesson.attendees.all()}
    response = tutor_api.post(
        f"/api/v1/lessons/{lesson.pk}/complete",
        {
            "attendance": [
                {"attendee": str(attendees[second.pk].pk), "outcome": "no_show"},
                {
                    "attendee": str(attendees[people["student"].pk].pk),
                    "outcome": "late",
                    "late_minutes": 10,
                },
            ]
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["status"] == "completed"
    rows = {a["student"]: a for a in body["attendees"]}
    assert rows[str(people["student"].pk)]["outcome"] == "late"
    assert rows[str(people["student"].pk)]["late_minutes"] == 10
    assert rows[str(second.pk)]["outcome"] == "no_show"
    assert rows[str(second.pk)]["charge_percent"] == "100.00"  # default no-show: charged
    [event] = events_of(org, "lesson.completed")
    assert {a["outcome"] for a in event["attendees"]} == {"late", "no_show"}
    assert event["tutors"][0]["pay_percent"] == "100.00"
    with tenant_context(org):
        report = LessonReport.objects.get(lesson=lesson)
    assert report.status == "pending"
    assert report.due_at == lesson.end + timedelta(hours=24)
    assert events_of(org, "lesson_report.requested")[0]["due_at"] == report.due_at.isoformat()


def test_absent_notified_is_not_charged_and_tutor_unpaid_if_nobody_came(org, staff, people):
    lesson = past(org, people)
    with tenant_context(org):
        attendee = lesson.attendees.get()
    staff.post(
        f"/api/v1/lessons/{lesson.pk}/complete",
        {"attendance": [{"attendee": str(attendee.pk), "outcome": "absent_notified"}]},
        format="json",
    )
    with tenant_context(org):
        attendee.refresh_from_db()
        assert (attendee.chargeable, attendee.charge_percent) == (False, Decimal(0))
        assert lesson.tutors.get().payable is False


def test_completion_window_and_future_lessons(org, staff, people):
    soon = future(org, people, hours=3)
    assert staff.post(f"/api/v1/lessons/{soon.pk}/complete").status_code == 422
    set_settings(org, "delivery", {"delivery.completion_opens": "near_end"})
    running = lesson_at(org, people, now() - timedelta(minutes=15), minutes=60)
    response = staff.post(f"/api/v1/lessons/{running.pk}/complete")
    assert response.status_code == 422
    assert "hasn't started" in response.json()["detail"]


def test_bill_actual_duration_reprices(org, staff, people):
    set_settings(org, "delivery", {"delivery.bill_actual_duration": True})
    lesson = past(org, people, hours=3)
    response = staff.post(
        f"/api/v1/lessons/{lesson.pk}/complete",
        {
            "actual_start": lesson.start.isoformat(),
            "actual_end": (lesson.start + timedelta(minutes=90)).isoformat(),
        },
        format="json",
    )
    assert response.status_code == 200, response.json()
    with tenant_context(org):
        attendee = lesson.attendees.get()
    assert attendee.charge_amount == Money("60.00", "GBP")  # £40/h for 90 minutes
    assert response.json()["actual_end"] is not None


class _Short:
    def shortfalls(self, lesson, charges):
        attendee = charges[0][0]
        return [
            balance.Shortfall(
                str(attendee.client_id),
                attendee.client.display_name,
                Money("0", "GBP"),
                Money("40", "GBP"),
            )
        ]


def test_negative_balance_blocks_tutors_and_staff_can_override(org, staff, tutor_api, people):
    lesson = past(org, people)
    balance.set_guard(_Short())
    try:
        response = tutor_api.post(f"/api/v1/lessons/{lesson.pk}/complete")
        assert response.status_code == 422
        assert response.json()["code"] == "insufficient_balance"
        assert "The Patels needs to top up" in response.json()["detail"]
        assert events_of(org, "lesson.completion_blocked")[0]["client_ids"] == [
            str(people["client"].pk)
        ]
        denied = tutor_api.post(
            f"/api/v1/lessons/{lesson.pk}/complete", {"override_balance": True}, format="json"
        )
        assert denied.status_code == 403
        ok = staff.post(
            f"/api/v1/lessons/{lesson.pk}/complete", {"override_balance": True}, format="json"
        )
        assert ok.json()["status"] == "completed"
    finally:
        balance.set_guard(balance._NoGuard())


def test_correct_attendance_after_completion(org, staff, people):
    lesson = past(org, people)
    staff.post(f"/api/v1/lessons/{lesson.pk}/complete")
    with tenant_context(org):
        attendee = lesson.attendees.get()
    response = staff.patch(
        f"/api/v1/lessons/{lesson.pk}/attendance",
        {"attendance": [{"attendee": str(attendee.pk), "outcome": "no_show"}]},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert response.json()["attendees"][0]["outcome"] == "no_show"
    assert events_of(org, "attendance.recorded")[0]["attendees"][0]["outcome"] == "no_show"
    with tenant_context(org):
        scheduling.set_lock([lesson], Lesson.Lock.INVOICED)
    locked = staff.patch(
        f"/api/v1/lessons/{lesson.pk}/attendance",
        {"attendance": [{"attendee": str(attendee.pk), "outcome": "present"}]},
        format="json",
    )
    assert locked.status_code == 422


# --- cancellation policies (T02) ----------------------------------------------------------------


def test_late_client_cancellation_preview_then_confirm(org, staff, people):
    lesson = future(org, people, hours=10)
    preview = staff.post(
        f"/api/v1/lessons/{lesson.pk}/cancel?preview=true",
        {"cancelled_by": "client", "reason": "Football"},
        format="json",
    ).json()
    assert preview["lesson"] is None
    outcome = preview["outcome"]
    assert (outcome["kind"], outcome["charge_percent"], outcome["pay_percent"]) == (
        "late",
        "100.00",
        "50.00",
    )
    assert outcome["message"] == (
        "This is a late cancellation: client charged 100%, tutor paid 50%."
    )
    with tenant_context(org):
        lesson.refresh_from_db()
    assert lesson.status == "planned"

    done = staff.post(
        f"/api/v1/lessons/{lesson.pk}/cancel",
        {"cancelled_by": "client", "reason": "Football"},
        format="json",
    ).json()
    assert done["lesson"]["status"] == "cancelled"
    assert done["lesson"]["cancelled_by"] == "client"
    attendee = done["lesson"]["attendees"][0]
    assert (attendee["outcome"], attendee["chargeable"]) == ("cancelled_client", True)
    assert done["lesson"]["tutors"][0]["pay_percent"] == "50.00"
    [event] = events_of(org, "lesson.cancelled")
    assert (event["policy_kind"], event["chargeable"]) == ("late", True)
    assert event["attendees"][0]["charge_percent"] == "100.00"
    with tenant_context(org):
        record = CancellationRecord.objects.get(lesson=lesson)
    assert record.kind == "late"
    assert 9 * 60 <= record.notice_minutes <= 10 * 60
    assert record.policy_snapshot["rules"]["free_window_hours"] == 24


def test_free_cancellations_and_monthly_limit(org, staff, people):
    with tenant_context(org):
        services.save_policy(
            name="House rules",
            scope_type="organisation",
            rules={"max_free_per_month": 1, "free_window_hours": 24},
        )
    first, second = future(org, people, hours=72), future(org, people, hours=96)
    one = staff.post(
        f"/api/v1/lessons/{first.pk}/cancel", {"cancelled_by": "client"}, format="json"
    ).json()
    assert one["outcome"]["kind"] == "free"
    assert one["lesson"]["attendees"][0]["chargeable"] is False
    two = staff.post(
        f"/api/v1/lessons/{second.pk}/cancel?preview=1", {"cancelled_by": "client"}, format="json"
    ).json()
    assert two["outcome"]["kind"] == "late"  # the free one this month is used up


def test_override_needs_permission_and_is_audited(org, staff, tutor_api, people):
    lesson = future(org, people, hours=5)
    body = {
        "cancelled_by": "client",
        "override": {"charge_percent": "0", "pay_percent": "100", "reason": "Goodwill"},
    }
    assert (
        tutor_api.post(f"/api/v1/lessons/{lesson.pk}/cancel", body, format="json").status_code
        == 403
    )
    done = staff.post(f"/api/v1/lessons/{lesson.pk}/cancel", body, format="json").json()
    assert done["outcome"]["policy_charge_percent"] == "100.00"
    assert done["outcome"]["charge_percent"] == "0.00"
    with tenant_context(org):
        record = CancellationRecord.objects.get(lesson=lesson)
        assert (record.overridden, record.override_reason) == (True, "Goodwill")
        assert AuditEntry.objects.filter(action="override_policy").exists()


def test_most_specific_policy_wins_and_versions_are_kept(org, staff, people):
    response = staff.post(
        "/api/v1/cancellation-policies",
        {"name": "Default", "scope_type": "organisation", "rules": {"free_window_hours": 48}},
        format="json",
    )
    assert response.status_code == 201, response.json()
    staff.post(
        "/api/v1/cancellation-policies",
        {
            "name": "Patels",
            "scope_type": "client",
            "scope_id": str(people["client"].pk),
            "rules": {"late_cancellation": {"charge_percent": 50, "pay_percent": 25}},
        },
        format="json",
    )
    lesson = future(org, people, hours=30)
    with tenant_context(org):
        resolved = policies.resolve(lesson)
    assert resolved.policy.name == "Patels"
    assert resolved.percents("late_cancellation") == (Decimal(50), Decimal(25))
    default_id = response.json()["id"]
    updated = staff.put(
        f"/api/v1/cancellation-policies/{default_id}",
        {"name": "Default", "scope_type": "organisation", "rules": {"free_window_hours": 12}},
        format="json",
    ).json()
    assert updated["version"] == 2
    assert updated["rules"]["free_window_hours"] == 12
    with tenant_context(org):
        assert CancellationPolicy.objects.filter(scope_type="organisation").count() == 2
    names = [p["name"] for p in staff.get("/api/v1/cancellation-policies").json()]
    assert sorted(names) == ["Default", "Patels"]
    bad = staff.post(
        "/api/v1/cancellation-policies",
        {"name": "X", "scope_type": "service", "scope_id": str(people["service"].pk),
         "rules": {"no_show": {"charge_percent": 150, "pay_percent": 0}}},
        format="json",
    )  # fmt: skip
    assert bad.status_code == 400


def test_series_cancellation_cancels_following(org, staff, people):
    with tenant_context(org):
        result = scheduling.create_series(
            service=people["service"],
            start_date=(now() + timedelta(days=2)).date(),
            start_time=now().time().replace(hour=16, minute=0, second=0, microsecond=0),
            duration_minutes=60,
            rrule="FREQ=WEEKLY",
            count=4,
            timezone="Europe/London",
            attendees=[{"student": people["student"]}],
            tutors=[{"tutor": people["tutor"]}],
        )
    first = result.created[0]
    done = staff.post(
        f"/api/v1/lessons/{first.pk}/cancel",
        {"cancelled_by": "client", "scope": "following", "reason": "Stopping"},
        format="json",
    ).json()
    assert done["following_cancelled"] == 3
    with tenant_context(org):
        assert Lesson.objects.filter(status="cancelled").count() == 4


# --- makeup credits (T03) -----------------------------------------------------------------------


def test_tutor_cancellation_issues_makeup_credit_that_can_be_used_once(org, staff, people):
    with tenant_context(org):
        services.save_policy(
            name="Default",
            scope_type="organisation",
            rules={"makeup_credit": {"on_tutor_cancellation": True, "valid_days": 30}},
        )
    lesson = future(org, people, hours=30)
    done = staff.post(
        f"/api/v1/lessons/{lesson.pk}/cancel", {"cancelled_by": "tutor"}, format="json"
    ).json()
    assert "makeup lesson credit" in done["outcome"]["message"]
    credits = staff.get(f"/api/v1/makeup-credits?student={people['student'].pk}").json()["results"]
    assert [c["status"] for c in credits] == ["available"]
    makeup = future(org, people, hours=100)
    used = staff.post(
        f"/api/v1/makeup-credits/{credits[0]['id']}/consume",
        {"lesson": str(makeup.pk)},
        format="json",
    )
    assert used.json()["status"] == "used"
    again = staff.post(
        f"/api/v1/makeup-credits/{credits[0]['id']}/consume",
        {"lesson": str(makeup.pk)},
        format="json",
    )
    assert again.status_code == 422
    with tenant_context(org):
        assert selectors.makeup_students(makeup) == {str(people["student"].pk)}
        credit = MakeupCredit.objects.get()
        assert credit.status_at(credit.expires_at + timedelta(seconds=1)) == "used"
    assert events_of(org, "makeup_credit.consumed")


def test_makeup_credit_expiry_extend_and_void(org, people, tenant):
    lesson = future(org, people, hours=30)
    credit = services.issue_makeup_credit(lesson, lesson.attendees.get(), days=1)
    assert credit.status_at(now() + timedelta(days=2)) == "expired"
    services.extend_makeup_credit(credit, until=now() + timedelta(days=10))
    assert credit.status_at(now() + timedelta(days=2)) == "available"
    services.void_makeup_credit(credit, note="Left")
    assert credit.status_at(now()) == "void"


# --- report templates (T04) ---------------------------------------------------------------------


FIELDS = [
    {"key": "covered", "label": "Covered", "type": "rich_text", "required": True,
     "visibility": "student"},
    {"key": "effort", "label": "Effort", "type": "rating", "visibility": "client"},
    {"key": "topics", "label": "Topics", "type": "checklist", "options": ["Algebra", "Ratio"],
     "visibility": "client"},
    {"key": "private", "label": "Private", "type": "text", "visibility": "staff"},
]  # fmt: skip


def test_templates_version_and_resolve_by_job_service_default(org, staff, people):
    with tenant_context(org):
        default = services.ensure_default_template()
    assert [f["key"] for f in default.current_version.fields] == [
        "covered",
        "homework",
        "parent_notes",
        "private_notes",
    ]
    created = staff.post(
        "/api/v1/report-templates",
        {"name": "Maths", "fields": FIELDS, "services": [str(people["service"].pk)]},
        format="json",
    )
    assert created.status_code == 201, created.json()
    template_id = created.json()["id"]
    lesson = future(org, people)
    with tenant_context(org):
        assert services.resolve_template(lesson).name == "Maths"
    changed = staff.patch(
        f"/api/v1/report-templates/{template_id}",
        {"fields": [*FIELDS, {"key": "next", "label": "Next", "type": "next_steps"}]},
        format="json",
    ).json()
    assert changed["version"] == 2
    renamed = staff.patch(
        f"/api/v1/report-templates/{template_id}", {"name": "Maths v2"}, format="json"
    ).json()
    assert renamed["version"] == 2  # no field change, no new version
    bad = staff.post(
        "/api/v1/report-templates",
        {"name": "Bad", "fields": [{"key": "a", "label": "A", "type": "select"}]},
        format="json",
    )
    assert bad.status_code == 422
    assert staff.delete(f"/api/v1/report-templates/{template_id}").status_code == 204
    with tenant_context(org):
        assert services.resolve_template(lesson).name == "Simple"


def test_answer_validation_and_visibility():
    fields = templates.clean_fields(FIELDS)
    with pytest.raises(BusinessRuleViolation):
        templates.clean_answers(fields, {"effort": 9})
    with pytest.raises(BusinessRuleViolation):
        templates.clean_answers(fields, {"topics": ["Calculus"]})
    with pytest.raises(BusinessRuleViolation) as missing:
        templates.clean_answers(fields, {"effort": 4}, require=True)
    assert "covered" in missing.value.extra["errors"]
    answers = templates.clean_answers(
        fields, {"covered": "Fractions", "effort": 4, "private": "Tired", "junk": 1}
    )
    assert "junk" not in answers
    assert templates.visible_answers(fields, answers, "client") == {
        "covered": "Fractions",
        "effort": 4,
    }
    assert templates.visible_answers(fields, answers, "student") == {"covered": "Fractions"}
    assert templates.visible_answers(fields, answers, "staff") == answers


# --- reports (T05) ------------------------------------------------------------------------------


def open_report(api, lesson):
    response = api.post(f"/api/v1/lessons/{lesson.pk}/reports", {}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_tutor_writes_and_submits_report_which_completes_and_shares(org, tutor_api, people):
    lesson = past(org, people)
    report = open_report(tutor_api, lesson)
    assert report["status"] == "pending"
    assert report["template_fields"][0]["key"] == "covered"
    draft = tutor_api.put(
        f"/api/v1/lesson-reports/{report['id']}",
        {"answers": {"homework": "Page 4"}},
        format="json",
    )
    assert draft.json()["status"] == "draft"
    missing = tutor_api.post(f"/api/v1/lesson-reports/{report['id']}/submit", {}, format="json")
    assert missing.status_code == 422
    assert "covered" in missing.json()["errors"]
    done = tutor_api.post(
        f"/api/v1/lesson-reports/{report['id']}/submit",
        {"answers": {"covered": "Fractions", "homework": "Page 4"}},
        format="json",
    ).json()
    assert done["status"] == "submitted"
    assert done["sla_state"] == "shared"  # auto-shared (no approval step)
    assert done["lesson_status"] == "completed"  # submitting completed the lesson
    assert events_of(org, "lesson_report.shared")[0]["client_ids"] == [str(people["client"].pk)]


def test_edit_window_and_staff_edits(org, staff, tutor_api, people, monkeypatch):
    lesson = past(org, people)
    report = open_report(tutor_api, lesson)
    tutor_api.post(
        f"/api/v1/lesson-reports/{report['id']}/submit",
        {"answers": {"covered": "Fractions"}},
        format="json",
    )
    later = now() + timedelta(hours=49)
    monkeypatch.setattr("tutortrack.delivery.services.now", lambda: later)
    late = tutor_api.put(
        f"/api/v1/lesson-reports/{report['id']}", {"answers": {"covered": "x"}}, format="json"
    )
    assert late.status_code == 403
    edited = staff.put(
        f"/api/v1/lesson-reports/{report['id']}",
        {"answers": {"covered": "Decimals"}},
        format="json",
    )
    assert edited.json()["answers"]["covered"] == "Decimals"


def test_approval_flow_return_approve_share(org, staff, tutor_api, people):
    set_settings(org, "delivery", {"delivery.report_approval_required": True})
    lesson = past(org, people)
    report = open_report(tutor_api, lesson)
    url = f"/api/v1/lesson-reports/{report['id']}"
    tutor_api.post(f"{url}/submit", {"answers": {"covered": "Ratio"}}, format="json")
    queue = staff.get("/api/v1/lesson-reports?sla=awaiting_approval").json()["results"]
    assert [r["id"] for r in queue] == [report["id"]]
    assert staff.post(f"{url}/share").status_code == 422  # needs approval first
    assert tutor_api.post(f"{url}/approve").status_code == 403
    returned = staff.post(f"{url}/return", {"note": "Add homework"}, format="json").json()
    assert (returned["status"], returned["returned_note"]) == ("returned", "Add homework")
    tutor_api.post(f"{url}/submit", {"answers": {"covered": "Ratio, p.5"}}, format="json")
    approved = staff.post(f"{url}/approve").json()
    assert approved["status"] == "approved"
    assert approved["sla_state"] == "shared"


def test_comments_and_tutor_sees_only_own_reports(org, staff, tutor_api, people):
    mine = past(org, people)
    other_tutor = TutorProfileFactory(organisation=org, status="active")
    theirs = past(org, people, hours=5, tutors=[{"tutor": other_tutor}])
    report = open_report(tutor_api, mine)
    with tenant_context(org):
        services.open_report(theirs, other_tutor)
    ids = {r["id"] for r in tutor_api.get("/api/v1/lesson-reports").json()["results"]}
    assert ids == {report["id"]}
    assert len(staff.get("/api/v1/lesson-reports").json()["results"]) == 2
    posted = staff.post(
        f"/api/v1/lesson-reports/{report['id']}/comments",
        {"body": "Lovely work", "visibility": "client"},
        format="json",
    )
    assert posted.status_code == 201
    comments = tutor_api.get(f"/api/v1/lesson-reports/{report['id']}/comments").json()
    assert [c["body"] for c in comments] == ["Lovely work"]


# --- SLA steps (T06) ----------------------------------------------------------------------------


def test_overdue_list_hold_and_escalation(org, staff, tutor_api, people):
    set_settings(org, "delivery", {"delivery.hold_pay_overdue_reports": True})
    lesson = past(org, people, hours=30)  # ended 29h ago: report due 5h ago
    staff.post(f"/api/v1/lessons/{lesson.pk}/complete")
    with tenant_context(org):
        report = LessonReport.objects.get(lesson=lesson)
    overdue = tutor_api.get("/api/v1/lesson-reports?sla=overdue").json()["results"]
    assert [r["id"] for r in overdue] == [str(report.pk)]
    assert overdue[0]["sla_state"] == "overdue"
    with tenant_context(org):
        assert services.report_due_reminder(report.pk) is True
        assert services.mark_report_overdue(report.pk) is True
        assert services.mark_report_overdue(report.pk) is False  # once
        report.refresh_from_db()
        assert report.pay_held is True
        assert services.escalate_report(report.pk) is True
        assert Task.objects.filter(target_id=str(report.pk)).count() == 1
    assert events_of(org, "lesson_report.overdue")[0]["pay_held"] is True
    assert len(events_of(org, "lesson_report.escalated")) == 1
    tutor_api.post(
        f"/api/v1/lesson-reports/{report.pk}/submit",
        {"answers": {"covered": "Late but done"}},
        format="json",
    )
    with tenant_context(org):
        report.refresh_from_db()
        assert report.pay_held is False
        assert services.report_due_reminder(report.pk) is False  # written: no reminder
        assert selectors.lessons_with_open_reports([lesson.pk]) == set()


def test_reports_not_required_setting(org, staff, people):
    set_settings(org, "delivery", {"delivery.report_required": False})
    lesson = past(org, people)
    staff.post(f"/api/v1/lessons/{lesson.pk}/complete")
    with tenant_context(org):
        assert not LessonReport.objects.exists()


# --- unconfirmed lessons (T07) ------------------------------------------------------------------


def test_unconfirmed_queue_nudge_and_auto_complete(org, staff, people):
    stale = past(org, people, hours=30)
    recent = past(org, people, hours=2)
    rows = staff.get("/api/v1/unconfirmed-lessons").json()
    assert [r["id"] for r in rows] == [str(stale.pk)]
    nudged = staff.post(
        "/api/v1/unconfirmed-lessons", {"ids": [str(stale.pk)]}, format="json"
    ).json()
    assert nudged == {"nudged": 1}
    with tenant_context(org):
        stale.refresh_from_db()
    assert stale.unconfirmed_at is not None
    assert events_of(org, "lesson.unconfirmed")[0]["tutor_ids"] == [str(people["tutor"].pk)]
    with tenant_context(org):
        assert services.handle_unconfirmed(recent.pk) == "flagged"
        set_settings(org, "delivery", {"delivery.unconfirmed_action": "auto_complete"})
        assert services.handle_unconfirmed(stale.pk) == "auto_completed"
        assert services.handle_unconfirmed(stale.pk) == "resolved"
        stale.refresh_from_db()
    assert (stale.status, stale.auto_completed, stale.unconfirmed_at) == ("completed", True, None)
    bulk = staff.post(
        "/api/v1/lessons/bulk",
        {"action": "cancel", "ids": [str(recent.pk)], "cancelled_by": "tutor"},
        format="json",
    ).json()
    assert bulk["succeeded"] == [str(recent.pk)]


def test_attendance_stats(org, staff, people):
    for hours, outcome in ((50, "present"), (40, "no_show"), (30, "late"), (20, "present")):
        lesson = past(org, people, hours=hours)
        with tenant_context(org):
            services.complete_lesson(
                lesson,
                attendance=[services.AttendanceRow(lesson.attendees.get().pk, outcome)],
            )
    stats = staff.get(f"/api/v1/students/{people['student'].pk}/attendance").json()
    assert stats["lessons"] == 4
    assert stats["attended"] == 3
    assert stats["rate_percent"] == "75.0"
    assert stats["streak"] == 2
    assert stats["by_outcome"]["no_show"] == 1


# --- policy engine properties -------------------------------------------------------------------


@settings(max_examples=60, deadline=None)
@given(
    notice_hours=st.integers(min_value=-5, max_value=200),
    window=st.integers(min_value=0, max_value=96),
    used=st.integers(min_value=0, max_value=5),
    limit=st.one_of(st.none(), st.integers(min_value=0, max_value=5)),
    late_charge=st.integers(min_value=0, max_value=100),
)
def test_client_cancellation_is_free_only_with_notice_and_allowance(
    notice_hours, window, used, limit, late_charge
):
    rules = policies.clean_rules(
        {
            "free_window_hours": window,
            "max_free_per_month": limit,
            "late_cancellation": {"charge_percent": late_charge, "pay_percent": 0},
        }
    )

    class FakeLesson:
        start = now() + timedelta(hours=notice_hours)

    decision = policies.evaluate_cancellation(
        FakeLesson(),  # type: ignore[arg-type]
        cancelled_by="client",
        at=now(),
        free_used_this_month=used,
        resolved=policies.ResolvedPolicy(None, rules),
    )
    free = notice_hours * 60 >= window * 60 - 1 and (limit is None or used < limit)
    if decision.kind == "free":
        assert free
        assert decision.charge_percent == 0
    else:
        assert decision.charge_percent == Decimal(late_charge)
    assert Decimal(0) <= decision.pay_percent <= Decimal(100)


# --- tenant isolation ---------------------------------------------------------------------------


def _report(organisation):
    with tenant_context(organisation):
        client = ClientFactory(organisation=organisation)
        student = StudentFactory(organisation=organisation, client=client)
        tutor = TutorProfileFactory(organisation=organisation, status="active")
        service = ServiceFactory(organisation=organisation)
        start = snap(now() - timedelta(hours=3))
        lesson = scheduling.create_lesson(
            start=start, end=start + timedelta(hours=1), service=service,
            attendees=[{"student": student}], tutors=[{"tutor": tutor}],
            timezone="Europe/London",
        ).lesson  # fmt: skip
        return lesson, services.open_report(lesson, tutor)


class TestReportIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/lesson-reports"

    def make_object(self, organisation):
        return _report(organisation)[1]


class TestTemplateIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/report-templates"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return services.create_template(name="T", fields=FIELDS)


class TestPolicyIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/cancellation-policies"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return services.save_policy(name="P", scope_type="organisation")


class TestMakeupIsolation(TenantIsolationTestMixin):
    list_url = "/api/v1/makeup-credits"

    def make_object(self, organisation):
        lesson, _report_row = _report(organisation)
        with tenant_context(organisation):
            return services.issue_makeup_credit(lesson, lesson.attendees.get(), days=30)


def test_template_default_is_unique(tenant):
    a = services.create_template(name="A", fields=FIELDS, is_default=True)
    b = services.create_template(name="B", fields=FIELDS, is_default=True)
    a.refresh_from_db()
    assert (a.is_default, b.is_default) == (False, True)
    assert ReportTemplate.objects.filter(is_default=True).count() == 1
