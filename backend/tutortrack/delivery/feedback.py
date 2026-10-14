"""Client feedback micro-surveys (FR-09-9, E09-T09): the write side.

``LessonFeedbackWorkflow`` (see ``processes.py``) waits ``delivery.feedback_delay_hours``
after a lesson is completed, then calls ``send_for_lesson``: for each student who attended
it decides whether to ask (every Nth lesson with that tutor, starting with the first),
picks one contact who receives lesson updates and has not opted out, creates the
``LessonFeedback`` and sends the E13 ``lesson_feedback_request`` (category ``reports``, so
the comms preferences and unsubscribes apply). The family answers through a signed link
(``/feedback/<token>``). Low scores alert staff; five stars can invite an E25 review. When
the link expires the workflow calls ``expire_for_lesson``.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.core import signing
from django.db import transaction
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.time import now
from tutortrack.tenancy.settings_service import get_setting

from . import events
from .models import LessonFeedback

SALT = "lesson-feedback"
CONSENT_KEY = "lesson-feedback"  # an E29 consent type; a withdrawal stops the requests
ATTENDED = ("present", "late", "")


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


# --- tokens ---------------------------------------------------------------------------------


def token_for(feedback: LessonFeedback) -> str:
    return signing.dumps(str(feedback.pk), salt=f"{SALT}:{feedback.organisation_id}", compress=True)


def for_token(token: str) -> LessonFeedback:
    if not token or len(token) > 300:
        raise NotFound()
    try:
        pk = signing.loads(
            token, salt=f"{SALT}:{require_organisation_id()}", max_age=timedelta(days=90)
        )
    except signing.BadSignature:
        raise NotFound() from None
    found = (
        LessonFeedback.objects.select_related("lesson", "student", "tutor").filter(pk=pk).first()
    )
    if found is None:
        raise NotFound()
    return found


# --- sending (workflow activity) ------------------------------------------------------------


def _opted_out(contact: Any) -> bool:
    from tutortrack.privacy.models import ConsentRecord

    latest = (
        ConsentRecord.objects.filter(
            subject_type="people.contact",
            subject_id=str(contact.pk),
            consent_type__key=CONSENT_KEY,
        )
        .order_by("-recorded_at", "-id")
        .first()
    )
    return latest is not None and not latest.granted


def _recipient(attendee: Any) -> tuple[Any, str]:
    """(contact, skip reason): an adult learner answers for themselves; otherwise the
    family's contacts who receive lesson updates, primary first."""
    student = attendee.student
    client = attendee.client
    if student.contact_id and student.contact is not None:
        candidates = [student.contact]
    else:
        contacts = [
            c
            for c in client.contacts.all()
            if c.receives_reports and (c.email or c.mobile) and c.archived_at is None
        ]
        contacts.sort(key=lambda c: (c.pk != client.primary_contact_id, c.created_at))
        candidates = contacts
    if not candidates:
        return None, LessonFeedback.SkipReason.NO_RECIPIENT
    allowed = [c for c in candidates if not _opted_out(c)]
    if not allowed:
        return None, LessonFeedback.SkipReason.NO_CONSENT
    return allowed[0], ""


def _due(student_id: Any, tutor_id: Any, lesson: Any) -> bool:
    """Ask after the first lesson with this tutor and then every Nth."""
    from tutortrack.scheduling.models import Lesson, LessonAttendee

    every = max(1, int(get_setting("delivery.feedback_every_n_lessons")))
    attended = LessonAttendee.objects.filter(
        student_id=student_id,
        lesson__status=Lesson.Status.COMPLETED,
        lesson__start__lte=lesson.start,
        outcome__in=ATTENDED,
    )
    if tutor_id is not None:
        attended = attended.filter(lesson__tutors__tutor_id=tutor_id)
    count = attended.values("lesson_id").distinct().count()
    return count >= 1 and (count - 1) % every == 0


@transaction.atomic
def send_for_lesson(lesson_id: Any) -> list[str]:
    """Create and send the feedback requests for a completed lesson. Idempotent: a student
    already asked about this lesson is not asked again. Returns the ids sent."""
    from tutortrack.comms import services as comms
    from tutortrack.scheduling.models import Lesson

    if not get_setting("delivery.feedback_enabled"):
        return []
    lesson = (
        Lesson.objects.prefetch_related(
            "attendees__student__contact", "attendees__client__contacts", "tutors__tutor"
        )
        .filter(pk=lesson_id)
        .first()
    )
    if lesson is None or lesson.status != Lesson.Status.COMPLETED:
        return []
    first_tutor = next(iter(lesson.tutors.all()), None)
    tutor = first_tutor.tutor if first_tutor is not None else None
    expires_at = now() + timedelta(days=int(get_setting("delivery.feedback_expiry_days")))
    lesson_date = lesson.start.astimezone(ZoneInfo(lesson.timezone)).date()
    sent: list[str] = []
    for attendee in lesson.attendees.all():
        if attendee.outcome not in ATTENDED or attendee.student.archived_at is not None:
            continue
        if LessonFeedback.objects.filter(lesson=lesson, student_id=attendee.student_id).exists():
            continue
        if not _due(attendee.student_id, tutor.pk if tutor else None, lesson):
            continue
        contact, reason = _recipient(attendee)
        feedback = LessonFeedback.objects.create(
            lesson=lesson,
            student_id=attendee.student_id,
            client_id=attendee.client_id,
            contact=contact,
            tutor=tutor,
            lesson_date=lesson_date,
            branch_id=lesson.branch_id,
            status=LessonFeedback.Status.SKIPPED if reason else LessonFeedback.Status.SENT,
            skip_reason=reason,
            sent_at=None if reason else now(),
            expires_at=expires_at,
        )
        audit.record_create(feedback)
        if reason:
            continue
        token = token_for(feedback)
        payload = (str(feedback.pk), token)
        comms.notify_on_commit(
            "lesson_feedback_request", payload, key=f"lesson-feedback:{feedback.pk}"
        )
        publish(
            events.LessonFeedbackRequested(
                subject_id=feedback.pk,
                lesson_id=str(lesson.pk),
                student_id=str(attendee.student_id),
                tutor_id=str(tutor.pk) if tutor else None,
            ),
            branch_id=feedback.branch_id,
        )
        sent.append(str(feedback.pk))
    return sent


@transaction.atomic
def expire_for_lesson(lesson_id: Any) -> int:
    """The links ran out: unanswered requests become ``expired``."""
    count = 0
    for feedback in LessonFeedback.objects.select_for_update().filter(
        lesson_id=lesson_id, status=LessonFeedback.Status.SENT
    ):
        with audit.track(feedback, action="expire"):
            feedback.status = LessonFeedback.Status.EXPIRED
            feedback.save(update_fields=["status", "updated_at"])
        count += 1
    return count


# --- answering (public link) ----------------------------------------------------------------


@transaction.atomic
def answer(
    token: str, *, rating: Any, comment: str = "", stop_asking: bool = False
) -> LessonFeedback:
    """The family's answer: 1-5 stars and an optional comment. Answering twice is refused."""
    feedback = LessonFeedback.objects.select_for_update().get(pk=for_token(token).pk)
    if feedback.status == LessonFeedback.Status.ANSWERED:
        raise BusinessRuleViolation(
            _("Thank you, we already have your feedback."), extra={"code": "answered"}
        )
    if feedback.status != LessonFeedback.Status.SENT or feedback.expires_at <= now():
        raise BusinessRuleViolation(_("This link has expired."), extra={"code": "expired"})
    try:
        stars = int(rating)
    except (TypeError, ValueError):
        stars = 0
    if not 1 <= stars <= 5:
        raise _invalid("rating", _("Choose from 1 to 5 stars."))
    threshold = int(get_setting("delivery.feedback_alert_at_or_below"))
    low = stars <= threshold
    with audit.track(feedback, action="answer"):
        feedback.status = LessonFeedback.Status.ANSWERED
        feedback.rating = stars
        feedback.comment = comment.strip()[:2000]
        feedback.answered_at = now()
        feedback.low_score_alerted = low
        feedback.save()
    publish(
        events.LessonFeedbackReceived(
            subject_id=feedback.pk,
            lesson_id=str(feedback.lesson_id),
            student_id=str(feedback.student_id),
            tutor_id=str(feedback.tutor_id) if feedback.tutor_id else None,
            rating=stars,
            low=low,
        ),
        branch_id=feedback.branch_id,
    )
    if stop_asking and feedback.contact_id:
        # G6 (FR-29-3): "don't ask me again" is an E29 withdrawal, which ``_opted_out`` reads.
        from tutortrack.privacy.capture import record_ticked

        record_ticked(
            people={"people.contact": [feedback.contact_id]},
            keys=[CONSENT_KEY],
            method="form",
            source=f"lesson-feedback:{feedback.pk}",
            granted=False,
        )
    if low:
        _alert_low_score(feedback)
    elif stars == 5 and get_setting("delivery.feedback_invites_review"):
        _invite_review(feedback)
    return feedback


def _alert_low_score(feedback: LessonFeedback) -> None:
    from tutortrack.comms import services as comms

    student = feedback.student.first_name
    tutor = feedback.tutor.full_name if feedback.tutor else ""
    title = _("Low lesson rating: %(stars)s/5 for %(student)s") % {
        "stars": feedback.rating,
        "student": student,
    }
    body = _("Lesson on %(date)s with %(tutor)s.") % {
        "date": feedback.lesson_date.isoformat(),
        "tutor": tutor or _("no tutor"),
    }
    payload = (title, body, f"/lesson-feedback?rating=low&id={feedback.pk}")
    comms.notify_on_commit("staff_lesson_feedback_low", payload, key=f"low:{feedback.pk}")


def _invite_review(feedback: LessonFeedback) -> None:
    """E25: a delighted family is asked for a public review (once per family and tutor)."""
    from tutortrack.growth.models import ReviewRequest
    from tutortrack.growth.services import request_review

    request_review(
        client=feedback.client,
        tutor=feedback.tutor,
        student=feedback.student,
        contact=feedback.contact,
        trigger=ReviewRequest.Trigger.AUTOMATION,
    )


# --- staff actions --------------------------------------------------------------------------


@transaction.atomic
def withdraw(feedback: LessonFeedback) -> LessonFeedback:
    """Staff withdraw an open request (the link stops working)."""
    feedback = LessonFeedback.objects.select_for_update().get(pk=feedback.pk)
    if feedback.status != LessonFeedback.Status.SENT:
        raise BusinessRuleViolation(_("Only open requests can be withdrawn."))
    with audit.track(feedback, action="withdraw"):
        feedback.status = LessonFeedback.Status.EXPIRED
        feedback.save(update_fields=["status", "updated_at"])
    return feedback
