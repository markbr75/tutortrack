"""E33-T05: the lesson communications built-ins running on Temporal: report chasing to
escalation and stopping when the report is written, the feedback request, and a lesson
reminder."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.automations import services as automations
from tutortrack.automations.models import Automation, AutomationRun
from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.models import OutboxEvent
from tutortrack.core.time import now
from tutortrack.crm.models import Task
from tutortrack.delivery import services
from tutortrack.delivery.models import LessonFeedback, LessonReport
from tutortrack.people.tests.factories import ContactFactory
from tutortrack.tenancy import settings_service

from .test_delivery import lesson_at, people  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db(transaction=True)


def run_for(org, key: str, subject_id) -> AutomationRun:
    with tenant_context(org):
        return AutomationRun.objects.get(automation__builtin_key=key, subject_id=str(subject_id))


def count(org, kind: str) -> int:
    with tenant_context(org):
        return OutboxEvent.objects.filter(event_type=kind).count()


def completed_report(org, people):  # noqa: F811
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    with tenant_context(org):
        services.complete_lesson(lesson)
        return lesson, LessonReport.objects.get(lesson=lesson)


def test_report_chasing_reminds_marks_overdue_and_escalates(org, people, temporal_env):  # noqa: F811
    with tenant_context(org):
        settings_service.update_settings("delivery", {"delivery.hold_pay_overdue_reports": True})
        automations.install_builtins()
    dispatch_batch()
    _lesson, report = completed_report(org, people)
    dispatch_batch()  # lesson_report.requested starts the run
    run = run_for(org, "report_chasing", report.pk)
    assert temporal_env.result(run.workflow_id) == "completed"
    for kind in ("lesson_report.due", "lesson_report.overdue", "lesson_report.escalated"):
        assert count(org, kind) == 1, kind
    with tenant_context(org):
        report.refresh_from_db()
        assert report.pay_held is True
        assert Task.objects.filter(target_id=str(report.pk)).exists()


def test_writing_the_report_stops_the_chasing(org, people, temporal_env):  # noqa: F811
    with tenant_context(org):
        automations.install_builtins()
    dispatch_batch()
    _lesson, report = completed_report(org, people)
    dispatch_batch()
    with tenant_context(org):
        services.submit_report(report, answers={"covered": "Fractions"})
    dispatch_batch()  # lesson_report.submitted: Stop when
    run = run_for(org, "report_chasing", report.pk)
    assert temporal_env.result(run.workflow_id) == "stopped"
    assert count(org, "lesson_report.overdue") == 0


def test_the_feedback_request_is_sent_and_unanswered_links_close(org, people, temporal_env):  # noqa: F811
    ContactFactory(organisation=org, client=people["client"], email="p@example.com")
    with tenant_context(org):
        settings_service.update_settings(
            "delivery", {"delivery.report_required": False, "delivery.feedback_every_n_lessons": 1}
        )
        automations.install_builtins()
        automations.set_enabled(Automation.objects.get(builtin_key="lesson_feedback"), True)
    dispatch_batch()
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    with tenant_context(org):
        services.complete_lesson(lesson)
    dispatch_batch()  # lesson.completed starts the run: 2 hours, ask, a week, close
    run = run_for(org, "lesson_feedback", lesson.pk)
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        assert LessonFeedback.objects.get(lesson=lesson).status == "expired"


def test_a_lesson_reminder_run_sends_the_reminder(org, people, temporal_env):  # noqa: F811
    ContactFactory(organisation=org, client=people["client"], email="p@example.com")
    with tenant_context(org):
        automations.install_builtins()
        reminders = Automation.objects.get(builtin_key="lesson_reminders")
    lesson = lesson_at(org, people, now() + timedelta(hours=2) - timedelta(minutes=10))
    with tenant_context(org):
        assert automations.fan_out(str(reminders.pk)) == 1  # the 2-hour reminder
    run = run_for(org, "lesson_reminders", lesson.pk)
    assert temporal_env.result(run.workflow_id) == "completed"
    with tenant_context(org):
        assert Message.objects.filter(type_key="lesson_reminder").exists()
