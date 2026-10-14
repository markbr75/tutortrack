"""E21-T06 progress reports: generated from attendance, lesson reports, topics, goals,
assessments and homework; tutor summary; approval; sharing to the portal and as a PDF;
the AI-draft seam for E31 (FR-21-6)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core import mail

from tutortrack.comms.models import Message
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.delivery import services as delivery
from tutortrack.learning import progress, services
from tutortrack.learning.models import ProgressReport
from tutortrack.scheduling.models import LessonAttendee

from .conftest import at, events_of, lesson_for, set_learning

pytestmark = pytest.mark.django_db

URL = "/api/v1/learning/progress-reports"


@pytest.fixture
def term(org, world):
    """Three lessons (present, late, no-show), a report with a staff-only note, a topic,
    a goal, a mock result and homework, all for Arjun this month."""
    student = world["student"]
    lessons = [lesson_for(org, world, at(-d), [student]) for d in (9, 6, 3)]
    with tenant_context(org):
        for lesson, outcome in zip(lessons, ("present", "late", "no_show"), strict=True):
            LessonAttendee.objects.filter(lesson=lesson).update(outcome=outcome)
        report = delivery.open_report(lessons[0], world["tutor"])
        delivery.submit_report(
            report,
            answers={
                "covered": "<p>Equivalent fractions</p>",
                "parent_notes": "Keep practising times tables",
                "private_notes": "Seemed tired",
            },
        )
        curriculum = services.install_builtin("gcse-maths")
        services.tag_lesson(lessons[1], [curriculum.nodes.get(name="Fractions")])
        services.save_goal(
            None,
            student=student,
            title="Grade 7",
            target_grade="7",
            milestones=[{"title": "Mock", "done": True}, {"title": "Algebra"}],
        )
        mock = services.save_assessment(
            None,
            name="Mock",
            kind="mock_exam",
            held_on=services.org_today() - timedelta(days=2),
            max_score=Decimal(80),
        )
        services.record_result(assessment=mock, student=student, score=Decimal(60))
        services.assign_homework(title="HW", due_at=at(1, 18), students=[student])
        today = services.org_today()
    return {"start": today - timedelta(days=20), "end": today + timedelta(days=5)}


def generate(org, world, term, student=None):
    with tenant_context(org):
        return services.generate_progress_report(
            student or world["student"], period_start=term["start"], period_end=term["end"]
        )


def test_snapshot_gathers_the_period(org, world, term):
    report = generate(org, world, term)
    snap = report.snapshot
    assert snap["attendance"] == {
        "lessons": 3,
        "attended": 2,
        "rate": "66.7",
        "by_outcome": {"present": 1, "late": 1, "no_show": 1},
    }
    assert [h["text"] for h in snap["highlights"]] == [
        "Equivalent fractions Keep practising times tables"
    ]  # staff-only notes and HTML are left out
    assert snap["topics"]["covered"][0]["name"] == "Fractions"
    assert snap["goals"][0]["progress_percent"] == 50
    assert snap["assessments"][0]["percent"] == "75.00"
    assert snap["homework"]["total"] == 1
    assert report.status == "draft"
    assert report.title.startswith("Progress report")


def test_bulk_generation_skips_submitted_reports(org, world, term):
    payload = {
        "period": "termly",
        "period_start": term["start"].isoformat(),
        "period_end": term["end"].isoformat(),
    }
    first = world["admin_api"].post(f"{URL}/generate", payload, format="json")
    assert first.json() == {"created": 1, "refreshed": 0, "skipped": 0}
    with tenant_context(org):
        report = ProgressReport.objects.get()
        services.update_progress_report(report, summary="Great term.")
        services.submit_progress_report(report)
    again = world["admin_api"].post(f"{URL}/generate", payload, format="json")
    assert again.json() == {"created": 0, "refreshed": 0, "skipped": 1}
    tutor = world["tutor_api"].post(f"{URL}/generate", payload, format="json")
    assert tutor.json()["skipped"] == 1  # only Arjun is Nia's


def test_approval_shares_with_the_family_and_sends_the_pdf(
    org, world, term, django_capture_on_commit_callbacks
):
    report = generate(org, world, term)
    url = f"{URL}/{report.pk}"
    no_summary = world["tutor_api"].post(f"{url}/submit")
    assert no_summary.status_code == 422
    world["tutor_api"].patch(url, {"summary": "Arjun has worked hard."}, format="json")
    submitted = world["tutor_api"].post(f"{url}/submit")
    assert submitted.json()["status"] == "submitted"
    assert world["family"]["api"].get("/api/v1/portal/learning/progress-reports").json() == []
    assert world["tutor_api"].post(f"{url}/approve").status_code == 403  # tutors can't approve
    approved = world["admin_api"].post(f"{url}/approve")
    assert approved.json()["status"] == "shared"  # learning.share_on_approval
    assert events_of(org, "progress_report.shared")[0]["data"]["client_id"] == str(
        world["family"]["client"].pk
    )
    portal = world["family"]["api"].get("/api/v1/portal/learning/progress-reports").json()
    assert [r["summary"] for r in portal] == ["Arjun has worked hard."]
    pdf = world["family"]["api"].get(f"/api/v1/portal/learning/progress-reports/{report.pk}/pdf")
    assert pdf["Content-Type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"
    assert (
        world["others"]["api"]
        .get(f"/api/v1/portal/learning/progress-reports/{report.pk}/pdf")
        .status_code
        == 404
    )
    with django_capture_on_commit_callbacks(execute=True):
        dispatch_batch()
    with tenant_context(org):
        assert Message.objects.filter(type_key="progress_report_shared", channel="email").exists()
    sent = [m for m in mail.outbox if m.attachments]
    assert sent
    assert sent[-1].attachments[0][0].startswith("progress-report-")
    edit = world["tutor_api"].patch(url, {"summary": "changed"}, format="json")
    assert edit.status_code == 409


def test_without_approval_submitting_shares(org, world, term):
    set_learning(org, progress_requires_approval=False)
    report = generate(org, world, term)
    with tenant_context(org):
        services.update_progress_report(report, summary="Lovely term.")
        done = services.submit_progress_report(report)
    assert done.status == "shared"


def test_approved_reports_can_be_reopened_until_shared(org, world, term):
    set_learning(org, share_on_approval=False)
    report = generate(org, world, term)
    with tenant_context(org):
        services.update_progress_report(report, summary="x")
        services.approve_progress_report(report)
    reopened = world["admin_api"].post(f"{URL}/{report.pk}/reopen")
    assert reopened.json()["status"] == "draft"
    refreshed = world["admin_api"].post(f"{URL}/{report.pk}/regenerate")
    assert refreshed.status_code == 200
    world["admin_api"].post(f"{URL}/{report.pk}/approve")
    shared = world["admin_api"].post(f"{URL}/{report.pk}/share")
    assert shared.json()["status"] == "shared"
    assert world["admin_api"].post(f"{URL}/{report.pk}/reopen").status_code == 409


def test_ai_draft_is_a_seam_for_e31(org, world, term):
    report = generate(org, world, term)
    body = world["tutor_api"].get(f"{URL}/{report.pk}").json()
    assert body["ai_draft_available"] is False
    missing = world["tutor_api"].post(f"{URL}/{report.pk}/draft-summary")
    assert missing.status_code == 403
    progress.register_drafter(lambda r: f"{r.snapshot['student']['name']} did well.")
    try:
        drafted = world["tutor_api"].post(f"{URL}/{report.pk}/draft-summary")
        assert drafted.json() == {"summary": f"{world['student'].full_name} did well."}
    finally:
        progress.register_drafter(None)


def test_tutors_only_see_and_write_their_students_reports(org, world, term):
    generate(org, world, term)
    stranger = generate(org, world, term, student=world["stranger"])
    ids = {r["id"] for r in world["tutor_api"].get(URL).json()["results"]}
    assert str(stranger.pk) not in ids
    assert len(ids) == 1
    denied = world["tutor_api"].post(
        URL,
        {
            "student": str(world["stranger"].pk),
            "period_start": term["start"].isoformat(),
            "period_end": term["end"].isoformat(),
        },
        format="json",
    )
    assert denied.status_code == 403
