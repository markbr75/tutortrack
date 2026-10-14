"""Learning records in DSARs and erasure (E21 data, E29 Part 2).

A student's learning record (homework and hand-ins, goals, assessment results, progress
reports, topic mastery, quiz attempts, resource activity) is wholly about them, so erasure
deletes it and releases the files. Library loans stay (they tie to replacement charges)
with their notes cleared."""

from __future__ import annotations

from typing import Any

from django.utils.translation import gettext as _

from tutortrack.privacy.registry import (
    ErasureContext,
    ErasureOutcome,
    Person,
    Provider,
    Section,
    register,
)

from .models import (
    AssessmentResult,
    Goal,
    HomeworkAssignment,
    HomeworkSubmission,
    Loan,
    ProgressReport,
    QuizAttempt,
    ResourceActivity,
    ResourceShare,
    TopicMastery,
)


def export(person: Person) -> list[Section]:
    students = person.of("people.student")
    if not students:
        return []
    homework = [
        {
            "id": str(a.pk),
            "title": a.homework.title,
            "due_at": a.due_at,
            "status": a.status,
            "grade": a.grade,
            "feedback": a.feedback,
            "submissions": [
                {"attempt": s.attempt, "body": s.body, "link": s.link, "submitted_at": s.created_at}
                for s in a.submissions.all()
            ],
        }
        for a in HomeworkAssignment.objects.filter(student_id__in=students)
        .select_related("homework")
        .prefetch_related("submissions")
    ]
    goals = [
        {
            "id": str(g.pk),
            "title": g.title,
            "description": g.description,
            "status": g.status,
            "target_grade": g.target_grade,
            "current_grade": g.current_grade,
        }
        for g in Goal.objects.filter(student_id__in=students)
    ]
    results = [
        {
            "id": str(r.pk),
            "assessment": r.assessment.name,
            "score": r.score,
            "grade": r.grade,
            "notes": r.notes,
            "taken_on": r.taken_on,
        }
        for r in AssessmentResult.objects.filter(student_id__in=students).select_related(
            "assessment"
        )
    ]
    reports = [
        {
            "id": str(p.pk),
            "title": p.title,
            "period_start": p.period_start,
            "period_end": p.period_end,
            "summary": p.summary,
            "status": p.status,
        }
        for p in ProgressReport.objects.filter(student_id__in=students)
    ]
    mastery = [
        {"id": str(m.pk), "topic": m.node.name, "level": m.level, "notes": m.notes}
        for m in TopicMastery.objects.filter(student_id__in=students).select_related("node")
    ]
    quizzes = [
        {
            "id": str(q.pk),
            "quiz": q.quiz.title,
            "score": q.score,
            "percent": q.percent,
            "submitted_at": q.submitted_at,
        }
        for q in QuizAttempt.objects.filter(student_id__in=students).select_related("quiz")
    ]
    loans = [
        {
            "id": str(loan.pk),
            "item": loan.item.name,
            "lent_on": loan.lent_on,
            "due_date": loan.due_date,
            "returned_on": loan.returned_on,
            "status": loan.status,
        }
        for loan in Loan.objects.filter(student_id__in=students).select_related("item")
    ]
    return [
        Section("learning.homework", _("Homework"), homework),
        Section("learning.goals", _("Goals"), goals),
        Section("learning.assessments", _("Assessment results"), results),
        Section("learning.progress_reports", _("Progress reports"), reports),
        Section("learning.topics", _("Topic progress"), mastery),
        Section("learning.quizzes", _("Quiz attempts"), quizzes),
        Section("learning.loans", _("Library loans"), loans),
    ]


def files(person: Person) -> list[Any]:
    students = person.of("people.student")
    out: list[Any] = []
    for submission in HomeworkSubmission.objects.filter(
        assignment__student_id__in=students
    ).prefetch_related("files"):
        out.extend(submission.files.all())
    out.extend(
        r.attachment
        for r in AssessmentResult.objects.filter(
            student_id__in=students, attachment__isnull=False
        ).select_related("attachment")
    )
    return out


def erase(person: Person, ctx: ErasureContext) -> ErasureOutcome:
    out = ErasureOutcome()
    students = person.of("people.student")
    if not students:
        return out
    for stored in files(person):
        out.file_ids.append(str(stored.pk))
    for submission in HomeworkSubmission.objects.filter(assignment__student_id__in=students):
        submission.files.clear()
    out.deleted += QuizAttempt.objects.filter(student_id__in=students).delete()[0]
    out.deleted += HomeworkAssignment.objects.filter(student_id__in=students).delete()[0]
    out.deleted += AssessmentResult.objects.filter(student_id__in=students).delete()[0]
    out.deleted += Goal.objects.filter(student_id__in=students).delete()[0]
    out.deleted += ProgressReport.objects.filter(student_id__in=students).delete()[0]
    out.deleted += TopicMastery.objects.filter(student_id__in=students).delete()[0]
    out.deleted += ResourceShare.objects.filter(student_id__in=students).delete()[0]
    out.deleted += ResourceActivity.objects.filter(student_id__in=students).delete()[0]
    out.anonymised += Loan.objects.filter(student_id__in=students).update(notes="", return_notes="")
    return out


register(
    Provider(
        key="learning", label="Learning records", export=export, files=files, erase=erase, order=32
    )
)
