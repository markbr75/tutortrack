"""E31-T02..T08 and FR-31-6 through the API, on the fake provider: what is sent is
pseudonymised and permission-scoped, drafts come back restored, proposals only run when
confirmed, and every request is logged and metered."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from tutortrack.ai.models import AIAssist, AIProposal, AIRequestLog, ThreadInsight
from tutortrack.core.context import tenant_context
from tutortrack.core.events.dispatcher import dispatch_batch
from tutortrack.crm.models import Task
from tutortrack.delivery import services as delivery
from tutortrack.leads import services as leads
from tutortrack.leads.models import Enquiry
from tutortrack.learning import progress as learning_progress
from tutortrack.learning import services as learning
from tutortrack.people.models import TutorSubject
from tutortrack.scheduling.models import Lesson

from .conftest import at, enable, lesson_for, sent_text, set_ai

pytestmark = pytest.mark.django_db

AI = "/api/v1/ai"


def _report(org: Any, world: dict[str, Any], days: int = -1) -> Any:
    lesson = lesson_for(org, world, at(days), [world["student"]])
    with tenant_context(org):
        return delivery.open_report(lesson, world["tutor"])


# --- T01: settings, status, usage, feedback ------------------------------------------------------


def test_status_settings_and_permissions(org, world, fake_llm):
    admin, tutor = world["admin_api"], world["tutor_api"]
    status = admin.get(f"{AI}/status").json()
    assert status["available"]
    assert status["provider"] == "fake"
    assert status["features"]["lesson_report"] is False
    assert status["credits"]["metered"] is False  # no subscription: unmetered
    assert tutor.get(f"{AI}/status").json()["credits"] is None  # no ai.usage.view
    changed = admin.patch(f"{AI}/features/lesson_report", {"enabled": True, "tone": "formal"})
    assert changed.status_code == 200
    row = next(r for r in changed.json() if r["feature"] == "lesson_report")
    assert row == {
        "feature": "lesson_report",
        "title": "Lesson report drafting",
        "enabled": True,
        "tone": "formal",
        "language": "",
    }
    assert tutor.patch(f"{AI}/features/inbox", {"enabled": True}).status_code == 403
    assert admin.patch(f"{AI}/features/nope", {"enabled": True}).status_code == 404
    assert tutor.get(f"{AI}/features").status_code == 200
    with tenant_context(org):
        from tutortrack.core.models import OutboxEvent

        assert OutboxEvent.objects.filter(event_type="ai_feature.updated").exists()


def test_disabled_feature_is_403(org, world, fake_llm):
    report = _report(org, world)
    response = world["tutor_api"].post(
        f"{AI}/lesson-reports/{report.pk}/draft", {"notes": "fractions"}
    )
    assert response.status_code == 403
    assert response.json()["type"].endswith("feature-disabled")
    assert fake_llm.requests == []


def test_feedback_keeps_edit_statistics_not_text(org, world, ai_on):
    report = _report(org, world)
    draft = (
        world["tutor_api"]
        .post(f"{AI}/lesson-reports/{report.pk}/draft", {"notes": "fractions, good effort"})
        .json()
    )
    response = world["tutor_api"].post(
        f"{AI}/feedback",
        {
            "request": draft["request"],
            "rating": "up",
            "draft_text": "Arjun worked hard.",
            "final_text": "Arjun worked very hard.",
        },
    )
    assert response.status_code == 200
    assert response.json()["rating"] == "up"
    assert 80 < response.json()["similarity_percent"] < 100
    # Someone else's request can't be rated.
    other = world["other_api"].post(
        f"{AI}/feedback", {"request": draft["request"], "rating": "down"}
    )
    assert other.status_code == 404


def test_usage_and_request_log(org, world, ai_on):
    report = _report(org, world)
    world["tutor_api"].post(f"{AI}/lesson-reports/{report.pk}/draft", {"notes": "fractions"})
    usage = world["admin_api"].get(f"{AI}/usage").json()
    assert usage["totals"]["requests"] == 1
    assert usage["totals"]["credits"] >= 1
    assert usage["by_feature"][0]["feature"] == "lesson_report"
    assert usage["by_user"][0]["requests"] == 1
    logs = world["admin_api"].get(f"{AI}/requests").json()["results"]
    assert logs[0]["prompt_key"] == "lesson_report.draft"
    assert logs[0]["status"] == "ok"
    assert world["tutor_api"].get(f"{AI}/requests").status_code == 403
    assert world["admin_api"].get(f"{AI}/usage?month=bad").status_code == 422


# --- T02: lesson report drafting (FR-31-1) --------------------------------------------------------


def test_lesson_report_draft_fills_the_template_and_marks_ai_assisted(org, world, ai_on):
    with tenant_context(org):
        curriculum = learning.install_builtin("gcse-maths")
        curriculum.subject = world["subject"]
        curriculum.save()
    report = _report(org, world)
    student = world["student"]
    response = world["tutor_api"].post(
        f"{AI}/lesson-reports/{report.pk}/draft",
        {"notes": f"{student.first_name} did fractions, really good effort today"},
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert set(body["answers"]) <= {"covered", "homework", "parent_notes", "private_notes"}
    assert body["answers"]["covered"].startswith("Covered:")
    assert student.first_name in body["answers"]["covered"]  # restored from the placeholder
    assert body["suggested_topics"]
    assert body["homework"]
    request = ai_on.requests[0]
    assert student.first_name not in str(request.messages)
    assert request.output_schema["properties"]["answers"]["required"]
    assert "Candidate curriculum topics" in request.messages[0]["content"]
    # The tutor applies the draft: the report is now AI-assisted.
    applied = world["tutor_api"].post(
        f"{AI}/assists",
        {"request": body["request"], "subject_type": "lesson_report", "subject_id": str(report.pk)},
    )
    assert applied.status_code == 201
    flags = (
        world["admin_api"]
        .get(f"{AI}/assists?subject_type=lesson_report&subject_id={report.pk}")
        .json()["results"]
    )
    assert len(flags) == 1
    assert flags[0]["feature"] == "lesson_report"


def test_lesson_report_voice_note(org, world, ai_on):
    from django.core.files.uploadedfile import SimpleUploadedFile

    report = _report(org, world)
    audio = SimpleUploadedFile("note.webm", b"We revised algebra and set worksheet 3", "audio/webm")
    response = world["tutor_api"].post(
        f"{AI}/lesson-reports/{report.pk}/draft", {"audio": audio}, format="multipart"
    )
    assert response.status_code == 200, response.content
    assert response.json()["transcript"] == "We revised algebra and set worksheet 3"
    assert "Voice note transcript" in ai_on.requests[0].messages[0]["content"]
    bad = SimpleUploadedFile("note.txt", b"x", "text/plain")
    rejected = world["tutor_api"].post(
        f"{AI}/lesson-reports/{report.pk}/draft", {"audio": bad}, format="multipart"
    )
    assert rejected.status_code == 422


def test_tutors_only_draft_their_own_reports(org, world, ai_on):
    report = _report(org, world)
    assert (
        world["other_api"]
        .post(f"{AI}/lesson-reports/{report.pk}/draft", {"notes": "x"})
        .status_code
        == 404
    )
    assert world["tutor_api"].post(f"{AI}/lesson-reports/{report.pk}/draft", {}).status_code == 422


# --- T03: progress reports and parent rewrite (FR-31-2) ------------------------------------------


def _progress(org: Any, world: dict[str, Any]) -> Any:
    lesson = lesson_for(org, world, at(-3), [world["student"]])
    with tenant_context(org):
        from tutortrack.scheduling.models import LessonAttendee

        LessonAttendee.objects.filter(lesson=lesson).update(outcome="present")
        today = learning.org_today()
        return learning.generate_progress_report(
            world["student"], period_start=today - timedelta(days=30), period_end=today
        )


def test_progress_comments_via_ai_endpoint_and_the_e21_seam(org, world, ai_on):
    from tutortrack.ai.features import progress

    learning_progress.register_drafter(progress.drafter, progress.available)
    report = _progress(org, world)
    url = f"/api/v1/learning/progress-reports/{report.pk}"
    assert world["tutor_api"].get(url).json()["ai_draft_available"] is True
    seam = world["tutor_api"].post(f"{url}/draft-summary")
    assert seam.status_code == 200
    assert world["student"].first_name in seam.json()["summary"]
    assert "attended 1 of 1 lessons" in seam.json()["summary"]
    direct = world["tutor_api"].post(f"{AI}/progress-reports/{report.pk}/draft")
    assert direct.status_code == 200
    assert direct.json()["request"]
    assert world["student"].last_name not in sent_text(ai_on)
    enable(org, "progress_report")
    with tenant_context(org):
        from tutortrack.ai import services

        services.update_feature("progress_report", enabled=False)
    assert world["tutor_api"].get(url).json()["ai_draft_available"] is False


def test_explain_to_parent_in_the_contacts_language(org, world, ai_on):
    contact = world["family"]["contact"]
    with tenant_context(org):
        contact.language = "fr"
        contact.save()
    response = world["admin_api"].post(
        f"{AI}/rewrite",
        {
            "text": "Secure at KS3 algebra.",
            "contact": str(contact.pk),
            "student": str(world["student"].pk),
        },
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["language"] == "fr"
    assert body["text"].startswith("(French)")
    assert "Key Stage 3" in body["text"]


# --- T04: enquiry extraction and triage (FR-31-4) -----------------------------------------------


ENQUIRY = (
    "Hi, I'm Priya Shah, my son Kabir needs GCSE maths and physics help before his mocks. "
    "Tuesdays after 4pm work best, online please. We're in LS6 2AB. Call me on 07700 900456 "
    "or priya.shah@example.com."
)


def test_extraction_prefills_and_contact_details_never_reach_the_model(org, world, ai_on):
    response = world["admin_api"].post(f"{AI}/enquiries/extract", {"text": ENQUIRY})
    assert response.status_code == 200, response.content
    data = response.json()["extracted"]
    assert data["contact"]["email"] == "priya.shah@example.com"
    assert data["contact"]["phone"] == "07700 900456"
    assert [s["subject"] for s in data["subjects"]] == ["Maths", "Physics"]
    assert data["subjects"][0]["level"] == "GCSE"
    assert data["location"]["postcode"] == "LS6 2AB"
    assert data["location"]["mode"] == "online"
    assert data["students"][0]["first_name"] == "Kabir"
    assert any("Tuesday" in a for a in data["availability"])
    assert ai_on.requests[0].tier == "fast"
    sent = sent_text(ai_on)
    assert "priya.shah@example.com" not in sent
    assert "07700" not in sent
    assert world["tutor_api"].post(f"{AI}/enquiries/extract", {"text": ENQUIRY}).status_code == 403


def test_triage_proposes_changes_that_apply_only_when_confirmed(org, world, ai_on):
    with tenant_context(org):
        enquiry = leads.create_enquiry(
            contact={"first_name": "Priya", "last_name": "Shah", "email": "p@example.com"},
            notes=ENQUIRY,
        )
    response = world["admin_api"].post(f"{AI}/enquiries/{enquiry.pk}/triage")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["next_steps"]
    assert body["reply_body"].startswith("Dear Priya Shah,")
    assert body["priority"] == "high"
    proposal = body["proposal"]
    assert proposal["action"] == "update_enquiry"
    assert proposal["status"] == "proposed"
    with tenant_context(org):
        assert Enquiry.objects.get(pk=enquiry.pk).priority == "normal"  # nothing changed yet
    confirmed = world["admin_api"].post(f"{AI}/proposals/{proposal['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "executed"
    with tenant_context(org):
        saved = Enquiry.objects.get(pk=enquiry.pk)
    assert saved.priority == "high"
    assert {s["subject"] for s in saved.subjects} == {"Maths", "Physics"}
    assert "Availability:" in saved.notes
    again = world["admin_api"].post(f"{AI}/proposals/{proposal['id']}/confirm")
    assert again.status_code == 409
    assert "Shah" not in sent_text(ai_on)


# --- T05: inbox (FR-31-3) -------------------------------------------------------------------------


def _inbound(org: Any, world: dict[str, Any], body: str) -> Any:
    from tutortrack.comms import inbox

    contact = world["family"]["contact"]
    with tenant_context(org):
        entry = inbox.receive_email(
            from_email=contact.email, from_name="Parent Patel", subject="Lessons", body=body
        )
        return entry.thread


def test_suggested_reply_uses_account_context(org, world, ai_on):
    lesson_for(org, world, at(3), [world["student"]])
    thread = _inbound(org, world, "Can we move Thursday's lesson to 5pm please?")
    response = world["admin_api"].post(f"{AI}/threads/{thread.pk}/reply")
    assert response.status_code == 200, response.content
    reply = response.json()["reply"]
    assert reply.startswith("Hi ")
    assert "Your next lesson is" in reply
    sent = ai_on.requests[0].messages[0]["content"]
    assert "Upcoming lesson:" in sent
    assert "Cancellation policy" in sent
    assert "Balance due" in sent
    assert world["student"].last_name not in sent_text(ai_on)


def test_summary_and_classification_with_routing_proposal(org, world, ai_on):
    thread = _inbound(org, world, "I'm unhappy that the tutor was late again.")
    summary = world["admin_api"].post(f"{AI}/threads/{thread.pk}/summary").json()
    assert summary["summary"]
    assert summary["action_items"]
    set_ai(org, inbox_routing={"complaint": str(world["admin"].pk)})
    classified = world["admin_api"].post(f"{AI}/threads/{thread.pk}/classify").json()
    assert classified["intent"] == "complaint"
    assert classified["confidence"] == 85
    assert classified["proposal"]["action"] == "assign_thread"
    insights = world["admin_api"].get(f"{AI}/thread-insights?thread={thread.pk}").json()
    assert insights["results"][0]["intent"] == "complaint"
    done = world["admin_api"].post(f"{AI}/proposals/{classified['proposal']['id']}/confirm")
    assert done.status_code == 200
    with tenant_context(org):
        thread.refresh_from_db()
    assert thread.assignee_id == world["admin"].pk


def test_flagged_conversations_get_no_ai(org, world, ai_on):
    thread = _inbound(org, world, "Hello")
    with tenant_context(org):
        thread.flagged = True
        thread.save()
    assert world["admin_api"].post(f"{AI}/threads/{thread.pk}/reply").status_code == 422
    assert ai_on.requests == []


def test_new_messages_are_classified_and_routed_automatically(
    org, world, ai_on, django_capture_on_commit_callbacks
):
    set_ai(org, inbox_auto_classify=True, inbox_routing={"billing": str(world["admin"].pk)})
    thread = _inbound(org, world, "Could you resend my invoice? I can't find the bill.")
    with django_capture_on_commit_callbacks(execute=True):
        dispatch_batch()
    with tenant_context(org):
        insight = ThreadInsight.objects.get(thread=thread)
        thread.refresh_from_db()
        log = AIRequestLog.objects.get(prompt_key="inbox.classify")
    assert insight.intent == "billing"
    assert thread.assignee_id == world["admin"].pk
    assert log.user_id is None
    assert log.model == "claude-haiku-5-5"


# --- T06: command bar (FR-31-5) -----------------------------------------------------------------


@pytest.fixture
def unique_student(org, world):
    """Both test families have an Arjun; give ours a name only one student has."""
    student = world["student"]
    with tenant_context(org):
        student.first_name = "Zebedee"
        student.save()
    return student


def test_command_bar_proposes_a_reschedule_and_runs_it_only_on_confirm(
    org, world, ai_on, unique_student
):
    student = unique_student
    first = lesson_for(org, world, at(2, hour=10), [student])
    second = lesson_for(org, world, at(9, hour=10), [student])
    weekday = first.start.astimezone(ZoneInfo("Europe/London")).strftime("%A")
    text = f"Move {student.first_name}'s {weekday} maths to 5pm"
    response = world["admin_api"].post(f"{AI}/command", {"text": text})
    assert response.status_code == 200, response.content
    body = response.json()
    assert len(body["proposals"]) == 1
    proposal = body["proposals"][0]
    assert proposal["action"] == "reschedule_lesson"
    assert "17:00" in proposal["summary"]
    assert student.first_name not in str(ai_on.requests[0].messages)  # primed placeholder
    with tenant_context(org):
        assert Lesson.objects.get(pk=first.pk).start == first.start  # nothing moved yet
    confirmed = world["admin_api"].post(f"{AI}/proposals/{proposal['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.content
    with tenant_context(org):
        moved = Lesson.objects.get(pk=first.pk)
        untouched = Lesson.objects.get(pk=second.pk)
    assert moved.start.astimezone(ZoneInfo("Europe/London")).hour == 17
    assert untouched.start == second.start
    listed = world["admin_api"].get(f"{AI}/proposals?status=executed").json()["results"]
    assert [p["id"] for p in listed] == [proposal["id"]]


def test_command_bar_respects_the_users_permissions(org, world, ai_on, unique_student):
    lesson = lesson_for(org, world, at(2), [world["student"]])
    weekday = lesson.start.astimezone(ZoneInfo("Europe/London")).strftime("%A")
    # The other tutor can't see Arjun: the lookup finds nobody, nothing is proposed.
    response = world["other_api"].post(
        f"{AI}/command", {"text": f"Move {world['student'].first_name}'s {weekday} lesson to 5pm"}
    )
    assert response.status_code == 200
    assert response.json()["proposals"] == []
    # Proposals can only be confirmed by the person they were made for.
    mine = (
        world["admin_api"]
        .post(
            f"{AI}/command",
            {"text": f"Move {world['student'].first_name}'s {weekday} lesson to 5pm"},
        )
        .json()["proposals"][0]
    )
    assert world["tutor_api"].post(f"{AI}/proposals/{mine['id']}/confirm").status_code == 404
    discarded = world["admin_api"].post(f"{AI}/proposals/{mine['id']}/discard")
    assert discarded.json()["status"] == "discarded"


def test_command_bar_tasks_and_tutor_search(org, world, ai_on):
    task = world["admin_api"].post(
        f"{AI}/command", {"text": "Remind me to call the Patels tomorrow"}
    )
    proposal = task.json()["proposals"][0]
    assert proposal["action"] == "create_task"
    world["admin_api"].post(f"{AI}/proposals/{proposal['id']}/confirm")
    with tenant_context(org):
        created = Task.objects.get()
    assert created.title.startswith("call the")
    assert created.assignee_id == world["admin"].pk
    search = (
        world["admin_api"]
        .post(f"{AI}/command", {"text": "Find a GCSE maths tutor free Tuesday evenings near LS6"})
        .json()
    )
    assert search["proposals"] == []
    criteria = search["searches"][0]
    assert criteria["subject"] == str(world["subject"].pk)
    assert criteria["weekday"] == "tuesday"
    assert criteria["postcode"] == "LS6"
    assert criteria["after_time"] == "17:00"


# --- T07: copilot (FR-31-7) ----------------------------------------------------------------------


def test_copilot_answers_from_reports_and_cites_them(org, world, ai_on):
    response = world["admin_api"].post(
        f"{AI}/copilot", {"question": "Which tutors had the most cancellations last month?"}
    )
    assert response.status_code == 200, response.content
    body = response.json()
    citation = body["citations"][0]
    assert citation["report"] == "cancellations"
    assert citation["index"] == 1
    assert citation["params"]["period"] == "last_month"
    assert citation["link"].startswith("/analytics/cancellations?")
    assert "[1]" in body["answer"]
    tools = [t["name"] for t in ai_on.requests[0].tools]
    assert tools == ["list_reports", "run_report"]
    with tenant_context(org):
        assert AIRequestLog.objects.get(prompt_key="copilot.answer").tool_rounds == 2


def test_copilot_needs_its_permission_and_only_sees_permitted_reports(org, world, ai_on):
    assert world["tutor_api"].post(f"{AI}/copilot", {"question": "Revenue?"}).status_code == 403
    from tutortrack.ai.redaction import Redactor
    from tutortrack.ai.tools import CopilotToolBox

    with tenant_context(org):
        toolbox = CopilotToolBox(world["tutor_user"], Redactor())
        visible = {r["key"] for r in toolbox.list_reports()["reports"]}
        result, is_error = toolbox.call("run_report", {"report": "revenue", "period": "this_month"})
    assert "revenue" not in visible
    assert is_error
    assert "error" in result


# --- T08: content (FR-31-8) and matching explanations (FR-31-6) ----------------------------------


def test_content_drafts(org, world, ai_on):
    broadcast = (
        world["admin_api"]
        .post(f"{AI}/content", {"kind": "broadcast", "brief": "Half-term revision sessions"})
        .json()
    )
    assert "{{ recipient.first_name }}" in broadcast["body"]
    assert broadcast["warnings"] == []
    bio = (
        world["admin_api"]
        .post(
            f"{AI}/content",
            {"kind": "bio", "brief": "GCSE specialist", "tutor": str(world["tutor"].pk)},
        )
        .json()
    )
    assert world["tutor"].first_name in bio["body"]
    assert world["tutor"].last_name not in sent_text(ai_on)
    job_ad = world["admin_api"].post(
        f"{AI}/content", {"kind": "job_ad", "brief": "Physics, Leeds", "subjects": ["Physics"]}
    )
    assert job_ad.status_code == 200
    assert job_ad.json()["title"]
    page = world["admin_api"].post(f"{AI}/content", {"kind": "page", "brief": "About us"}).json()
    assert page["meta_description"]
    assert (
        world["tutor_api"].post(f"{AI}/content", {"kind": "broadcast", "brief": "x"}).status_code
        == 403
    )
    own = world["tutor_api"].post(
        f"{AI}/content", {"kind": "bio", "brief": "x", "tutor": str(world["tutor"].pk)}
    )
    assert own.status_code == 200
    other = world["tutor_api"].post(
        f"{AI}/content", {"kind": "bio", "brief": "x", "tutor": str(world["other_tutor"].pk)}
    )
    assert other.status_code == 404


def test_matching_explanation(org, world, ai_on):
    with tenant_context(org):
        TutorSubject.objects.create(
            tutor=world["tutor"],
            subject="Maths",
            catalogue_subject=world["subject"],
            competency=TutorSubject.Competency.APPROVED,
            approved=True,
        )
    response = world["admin_api"].post(
        f"{AI}/matching/explain",
        {
            "tutor": str(world["tutor"].pk),
            "criteria": {"subject": str(world["subject"].pk), "mode": "online"},
        },
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert world["tutor"].first_name in body["explanation"]
    assert body["intro_message"]
    assert '"margin"' not in sent_text(ai_on)
    missing = world["admin_api"].post(
        f"{AI}/matching/explain",
        {"tutor": str(world["other_tutor"].pk), "criteria": {"subject": str(world["subject"].pk)}},
    )
    assert missing.status_code == 422


def test_proposals_cannot_run_actions_the_user_lacks(org, world, ai_on):
    from tutortrack.ai import services
    from tutortrack.core.exceptions import NotFound

    lesson = lesson_for(org, world, at(2), [world["student"]])
    with tenant_context(org), pytest.raises(NotFound):
        services.propose(
            world["other_tutor"].membership.user,
            action="reschedule_lesson",
            params={"lesson_id": str(lesson.pk), "new_start": "2026-11-01T17:00", "scope": "this"},
            feature="command_bar",
        )
    with tenant_context(org):
        assert not AIProposal.objects.exists()
        assert not AIAssist.objects.exists()
