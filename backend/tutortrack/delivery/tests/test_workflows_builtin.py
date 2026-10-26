"""E33-T05: the lesson communications built-in workflows: first versions from the settings,
the "near a date" start that lesson reminders and the unconfirmed lesson chaser use, the
lesson actions, and the replaced settings and processes."""

from __future__ import annotations

from datetime import timedelta

import pytest

from tutortrack.automations import services as automations
from tutortrack.automations.models import Automation, AutomationRun
from tutortrack.automations.tests.test_catalogue import act
from tutortrack.comms.models import OrgNotificationSetting
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.core.exceptions import BusinessRuleViolation
from tutortrack.core.models import OutboxEvent, WorkflowLink
from tutortrack.core.time import now
from tutortrack.delivery import services
from tutortrack.delivery.models import LessonFeedback, LessonReport
from tutortrack.delivery.processes import feedback_workflow_id, sla_workflow_id
from tutortrack.scheduling import services as scheduling
from tutortrack.tenancy import settings_service

from .test_delivery import lesson_at, people  # noqa: F401  (fixture)

pytestmark = pytest.mark.django_db

KEYS = {"lesson_reminders", "report_chasing", "lesson_feedback", "unconfirmed_lessons"}


def install(org, **settings) -> dict[str, Automation]:
    with tenant_context(org):
        if settings:
            settings_service.update_settings("delivery", settings, allow_replaced=True)
        automations.install_builtins()
        return {a.builtin_key: a for a in Automation.objects.filter(builtin_key__in=KEYS)}


def short(steps) -> list[str]:
    def one(s):
        if s["type"] == "action":
            return s["action"]
        if s.get("until"):
            return f"{s['offset_hours']:+}h from due"
        return f"wait {s.get('days', 0)}d{s.get('hours', 0)}h"

    return [one(s) for s in steps]


def launched(monkeypatch) -> list[AutomationRun]:
    started: list[AutomationRun] = []
    monkeypatch.setattr(automations, "launch", lambda run, **kw: started.append(run))
    return started


# --- first versions ------------------------------------------------------------------------


def test_with_the_default_settings_each_starts_as_the_default(org):
    installed = install(org)
    assert set(installed) == KEYS
    assert not any(a.edited for a in installed.values())
    assert {k for k, a in installed.items() if a.enabled} == {
        "lesson_reminders", "report_chasing", "unconfirmed_lessons",
    }  # fmt: skip
    reminders = installed["lesson_reminders"]
    assert (reminders.trigger_type, reminders.subject_type) == ("date", "lesson")
    assert reminders.trigger_config == {"subject": "lesson", "field": "start",
                                        "minutes": [-1440, -120]}  # fmt: skip
    assert reminders.conditions == {"predicate": "lesson.still_planned"}
    assert short(installed["report_chasing"].steps) == [
        "-4h from due", "remind_report_due", "+0h from due", "report_overdue",
        "+24h from due", "escalate_report",
    ]  # fmt: skip
    assert installed["report_chasing"].stop_when == ["lesson_report.submitted"]
    assert short(installed["lesson_feedback"].steps) == [
        "wait 0d2h", "send_feedback_survey", "wait 7d0h", "expire_feedback",
    ]  # fmt: skip
    assert installed["unconfirmed_lessons"].trigger_config["minutes"] == [24 * 60]


def test_each_takes_the_settings_it_replaces(org):
    with tenant_context(org):
        OrgNotificationSetting.objects.create(
            type_key="lesson_reminder", enabled=True, channels=["email"], timing=[30, 180]
        )
    installed = install(org, **{
        "delivery.report_reminder_hours": 0, "delivery.report_escalate_hours": 48,
        "delivery.feedback_enabled": True, "delivery.feedback_delay_hours": 0,
        "delivery.feedback_expiry_days": 3, "delivery.unconfirmed_after_hours": 12,
    })  # fmt: skip
    assert installed["lesson_reminders"].trigger_config["minutes"] == [-180, -30]
    assert short(installed["report_chasing"].steps) == [
        "+0h from due", "report_overdue", "+48h from due", "escalate_report",
    ]  # fmt: skip
    feedback = installed["lesson_feedback"]
    assert feedback.enabled
    assert short(feedback.steps) == ["send_feedback_survey", "wait 3d0h", "expire_feedback"]
    assert installed["unconfirmed_lessons"].trigger_config["minutes"] == [12 * 60]
    assert all(a.edited for a in installed.values())


def test_reminders_start_off_when_the_notification_was_off(org):
    with tenant_context(org):
        OrgNotificationSetting.objects.create(
            type_key="lesson_reminder", enabled=False, channels=["email"], timing=[]
        )
    reminders = install(org)["lesson_reminders"]
    assert not reminders.enabled
    assert reminders.trigger_config["minutes"] == [-1440, -120]
    with tenant_context(org):
        assert [n["name"] for n in automations.builtin_notices()] == ["Lesson reminders"]


# --- the "near a date" start -----------------------------------------------------------------


def test_reminders_start_for_lessons_whose_reminder_time_just_came(org, people, monkeypatch):  # noqa: F811
    reminders = install(org)["lesson_reminders"]
    soon = lesson_at(org, people, now() + timedelta(hours=24) - timedelta(minutes=30))
    later = lesson_at(org, people, now() + timedelta(hours=30))
    started = launched(monkeypatch)
    with tenant_context(org):
        assert automations.fan_out(str(reminders.pk)) == 1
        assert automations.fan_out(str(reminders.pk)) == 0  # once per lesson and time
    [run] = started
    assert run.subject_id == str(soon.pk)
    assert run.run_key == f"schedule:near:-1440:{soon.start.isoformat()}"
    # Moved a little later: a new run for its new time. The other lesson isn't due yet.
    with tenant_context(org):
        scheduling.update_lesson(
            soon, start=soon.start + timedelta(minutes=10), end=soon.end + timedelta(minutes=10),
            override_conflicts=True,
        )  # fmt: skip
        assert automations.fan_out(str(reminders.pk)) == 1
    assert str(later.pk) not in {r.subject_id for r in started}
    # A cancelled lesson isn't picked: "the lesson is still going ahead" isn't true.
    cancelled = lesson_at(org, people, now() + timedelta(hours=24) - timedelta(minutes=20))
    with tenant_context(org):
        scheduling.cancel_lesson(cancelled, reason="Ill")
        assert automations.fan_out(str(reminders.pk)) == 0


def test_unconfirmed_lessons_are_flagged_a_day_after_they_end(org, people, monkeypatch):  # noqa: F811
    chaser = install(org)["unconfirmed_lessons"]
    unmarked = lesson_at(org, people, now() - timedelta(hours=26))  # ended 25 hours ago
    lesson_at(org, people, now() - timedelta(hours=3))  # not yet a day
    started = launched(monkeypatch)
    with tenant_context(org):
        assert automations.fan_out(str(chaser.pk)) == 1
    assert [r.subject_id for r in started] == [str(unmarked.pk)]
    assert act(org, "handle_unconfirmed", "lesson", unmarked) == {"outcome": "flagged"}
    with tenant_context(org):
        unmarked.refresh_from_db()
        assert unmarked.unconfirmed_at is not None
        services.complete_lesson(unmarked)
    assert act(org, "handle_unconfirmed", "lesson", unmarked, step="b") == {
        "skipped": "the lesson has been marked"
    }


def test_near_starts_are_checked_when_saved(org):
    def save(config):
        with tenant_context(org):
            automations.create_automation(
                name="x", trigger_type="date", trigger_config=config,
                steps=[{"type": "action", "action": "send_lesson_reminder", "config": {}}],
            )  # fmt: skip

    base = {"subject": "lesson", "field": "start"}
    for bad in ({"minutes": []}, {"minutes": [99999999]}, {"minutes": ["60"]},
                {"minutes": [60], "catch_up_minutes": 5}):  # fmt: skip
        with pytest.raises(BusinessRuleViolation):
            save(base | bad)
    with pytest.raises(BusinessRuleViolation):  # a date without a time
        save({"subject": "student", "field": "date_of_birth", "minutes": [60]})
    save(base | {"minutes": [-60, 30], "catch_up_minutes": 120})


# --- actions ---------------------------------------------------------------------------------


def test_report_reminder_and_feedback_actions(org, people):  # noqa: F811
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    with tenant_context(org):
        services.complete_lesson(lesson)
        report = LessonReport.objects.get(lesson=lesson)
    assert act(org, "remind_report_due", "lesson_report", report) == {"reminded": str(report.pk)}
    with tenant_context(org):
        assert OutboxEvent.objects.filter(event_type="lesson_report.due").count() == 1
        LessonReport.objects.filter(pk=report.pk).update(status="submitted")
    assert act(org, "remind_report_due", "lesson_report", report, step="b") == {
        "skipped": "the report is written"
    }
    assert act(org, "expire_feedback", "lesson", lesson) == {
        "skipped": "every request was answered"
    }


# --- what they replaced ---------------------------------------------------------------------


def test_replaced_settings_and_reminder_timing_are_read_only(org, api):
    described = {d["key"]: d for d in api.get("/api/v1/settings/delivery").json()["schema"]}
    assert described["delivery.report_escalate_hours"]["replaced_by"] == "report_chasing"
    assert described["delivery.feedback_enabled"]["replaced_by"] == "lesson_feedback"
    assert described["delivery.unconfirmed_after_hours"]["replaced_by"] == "unconfirmed_lessons"
    assert "replaced_by" not in described["delivery.report_due_hours"]  # the deadline
    change = {"values": {"delivery.feedback_delay_hours": 1}}
    refused = api.patch("/api/v1/settings/delivery", change, format="json")
    assert refused.status_code == 400
    [reminder] = [s for s in api.get("/api/v1/notification-settings").json()
                  if s["key"] == "lesson_reminder"]  # fmt: skip
    assert (reminder["has_timing"], reminder["timing_in_workflow"]) == (False, True)
    body = {"enabled": True, "channels": ["email"], "timing": [60]}
    timing = api.put("/api/v1/notification-settings/lesson_reminder", body, format="json")
    assert timing.status_code == 422
    channels = api.put("/api/v1/notification-settings/lesson_reminder",
                       {"enabled": True, "channels": ["email"]}, format="json")  # fmt: skip
    assert channels.status_code == 200, channels.content


def test_reports_and_completed_lessons_no_longer_start_the_old_workflows(org, people):  # noqa: F811
    lesson = lesson_at(org, people, now() - timedelta(hours=2))
    with tenant_context(org):
        services.complete_lesson(lesson)
        report = LessonReport.objects.get(lesson=lesson)
    dispatch_batch()
    with tenant_context(org):
        ids = [sla_workflow_id(org.pk, report.pk), feedback_workflow_id(org.pk, lesson.pk)]
        assert not WorkflowLink.objects.filter(workflow_id__in=ids).exists()
        assert not LessonFeedback.objects.exists()  # the built-in is off by default
