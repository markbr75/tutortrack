"""Lesson reports in DSARs, erasure and retention (E29 Part 2).

A report about a one-to-one lesson is wholly about that student, so erasing the student
clears its answers; on group lessons the student's name is scrubbed from the answers.
The ``lesson_reports`` retention category clears answers and comments after the period."""

from __future__ import annotations

from datetime import datetime

from django.db.models import Count, QuerySet
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    RetentionCategory,
    Section,
    register,
    register_retention,
)

from .models import (
    CancellationRecord,
    LessonFeedback,
    LessonReport,
    LessonReportComment,
    MakeupCredit,
)


def _reports(person: Person) -> QuerySet[LessonReport]:
    return LessonReport.objects.filter(
        lesson__attendees__student_id__in=person.of("people.student")
    ).distinct()


def _feedback(person: Person) -> QuerySet[LessonFeedback]:
    """E09-T09 surveys about the person's lessons or answered by them."""
    from django.db.models import Q

    return LessonFeedback.objects.filter(
        Q(student_id__in=person.of("people.student"))
        | Q(contact_id__in=person.of("people.contact"))
        | Q(client_id__in=person.of("people.client"))
    ).distinct()


def export(person: Person) -> list[Section]:
    reports = [
        {
            "id": str(r.pk),
            "lesson": r.lesson.title,
            "date": r.lesson.start,
            "status": r.status,
            "answers": r.answers,
            "shared_at": r.shared_at,
        }
        for r in _reports(person).select_related("lesson")
    ]
    comments = [
        {"id": str(c.pk), "body": c.body, "created_at": c.created_at}
        for c in LessonReportComment.objects.filter(author_id__in=person.of("identity.user"))
    ]
    credits = [
        {"id": str(m.pk), "expires_at": m.expires_at, "consumed_at": m.consumed_at}
        for m in MakeupCredit.objects.filter(student_id__in=person.of("people.student"))
    ]
    feedback = [
        {
            "id": str(f.pk),
            "lesson": f.lesson.title,
            "date": f.lesson_date,
            "status": f.status,
            "rating": f.rating,
            "comment": f.comment,
        }
        for f in _feedback(person).select_related("lesson")
    ]
    return [
        Section("delivery.reports", _("Lesson reports"), reports),
        Section("delivery.feedback", _("Lesson feedback you gave"), feedback),
        Section("delivery.comments", _("Comments on lesson reports"), comments),
        Section("delivery.makeup_credits", _("Make-up credits"), credits),
    ]


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    reports = _reports(person).annotate(n=Count("lesson__attendees"))
    for report in reports:
        answers = {} if report.n <= 1 else ctx.scrub_json(report.answers)
        if answers != report.answers:
            LessonReport.objects.filter(pk=report.pk).update(answers=answers)
            out.anonymised += 1
    users = person.of("identity.user")
    for comment in LessonReportComment.objects.filter(author_id__in=users):
        LessonReportComment.objects.filter(pk=comment.pk).update(
            body="", author_name=ctx.label("identity.user", comment.author_id, _("Erased person"))
        )
        out.anonymised += 1
    for comment in LessonReportComment.objects.filter(report__in=_reports(person)).exclude(
        author_id__in=users
    ):
        body = ctx.scrub(comment.body)
        if body != comment.body:
            LessonReportComment.objects.filter(pk=comment.pk).update(body=body)
            out.anonymised += 1
    out.anonymised += LessonFeedback.objects.filter(
        pk__in=_feedback(person).exclude(comment="").values("pk")
    ).update(comment="")
    for record in CancellationRecord.objects.filter(
        lesson__attendees__student_id__in=person.of("people.student")
    ).distinct():
        reason = ctx.scrub(record.reason)
        if reason != record.reason:
            CancellationRecord.objects.filter(pk=record.pk).update(reason=reason)
    return out


def _purge_reports(cutoff: datetime, dry_run: bool, limit: int) -> int:
    from tutortrack.privacy.selectors import held_ids

    qs = (
        LessonReport.objects.filter(lesson__start__lt=cutoff)
        .exclude(answers={})
        .exclude(lesson__attendees__student_id__in=list(held_ids("people.student")))
    )
    if dry_run:
        return qs.count()
    ids = list(qs.values_list("pk", flat=True)[:limit])
    LessonReportComment.objects.filter(report_id__in=ids).delete()
    return LessonReport.objects.filter(pk__in=ids).update(answers={})


register(Provider(key="delivery", label="Lesson reports", export=export, erase=erase, order=31))
register_retention(
    RetentionCategory(
        key="lesson_reports",
        label=gettext_lazy("Lesson report notes and comments"),
        default_days=365 * 6 + 2,
        purge=_purge_reports,
        order=20,
    )
)
