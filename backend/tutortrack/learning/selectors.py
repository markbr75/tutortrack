"""Learning reads (E21): scoped querysets, homework stats, topic coverage, assessment
trends and what a portal household may see."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Count, Max, Q, QuerySet

from tutortrack.core.permissions import permission_scope, scope_queryset
from tutortrack.core.time import now

from .models import (
    Assessment,
    AssessmentResult,
    Curriculum,
    CurriculumNode,
    Goal,
    GradeScale,
    Homework,
    HomeworkAssignment,
    LessonTopic,
    LibraryItem,
    Loan,
    ProgressReport,
    Quiz,
    QuizAttempt,
    Resource,
    ResourceFolder,
    ResourceShare,
    TopicMastery,
    tutor_students,
)


def scoped(user: Any, queryset: QuerySet[Any], codename: str) -> QuerySet[Any]:
    """``scope_queryset`` for every learning model: organisation-wide models (no branch)
    treat a branch grant as organisation-wide; ``own`` uses the model's ``own_scope_q``."""
    if hasattr(queryset.model, "branch_id"):
        return scope_queryset(user, queryset, codename)
    scope = permission_scope(user, codename)
    if scope is None:
        return queryset.none()
    if scope == "own":
        own_q = getattr(queryset.model, "own_scope_q", None)
        return queryset.filter(own_q(user)).distinct() if callable(own_q) else queryset.none()
    return queryset


def can_see_student(user: Any, student: Any, codename: str) -> bool:
    scope = permission_scope(user, codename)
    if scope is None:
        return False
    if scope == "own":
        return tutor_students(user).filter(pk=student.pk).exists()
    return True


# --- resources ----------------------------------------------------------------------------------


def folders(user: Any) -> QuerySet[ResourceFolder]:
    return scoped(user, ResourceFolder.objects.all(), "learning.resource.view")


def resources(user: Any) -> QuerySet[Resource]:
    """Staff see every library (for support); tutors see their own resources, the
    organisation library open to tutors and what is shared with their students."""
    return scoped(user, Resource.objects.select_related("file", "owner"), "learning.resource.view")


def resource_shares(user: Any) -> QuerySet[ResourceShare]:
    visible = resources(user).values("pk")
    return ResourceShare.objects.filter(resource__in=visible).select_related(
        "student", "job", "lesson", "group_class"
    )


def storage_usage() -> dict[str, Any]:
    from django.db.models import Sum

    from tutortrack.core import entitlements
    from tutortrack.core.models import StoredFile

    used = StoredFile.objects.exclude(status=StoredFile.Status.REJECTED).aggregate(
        total=Sum("size_bytes")
    )["total"]
    library = Resource.objects.filter(kind=Resource.Kind.FILE).aggregate(
        total=Sum("file__size_bytes")
    )["total"]
    return {
        "used_bytes": int(used or 0),
        "library_bytes": int(library or 0),
        "limit_gb": entitlements.limit("storage_gb"),
    }


# --- homework -----------------------------------------------------------------------------------


def grade_scales() -> QuerySet[GradeScale]:
    return GradeScale.objects.filter(archived_at__isnull=True)


def homework(user: Any) -> QuerySet[Homework]:
    return scoped(user, Homework.objects.select_related("set_by", "quiz"), "learning.homework.view")


def assignments(
    user: Any, codename: str = "learning.homework.view"
) -> QuerySet[HomeworkAssignment]:
    return scoped(
        user,
        HomeworkAssignment.objects.select_related("homework", "student"),
        codename,
    )


def homework_stats(qs: QuerySet[HomeworkAssignment]) -> dict[str, Any]:
    """Completion stats over ``qs`` (FR-21-2): due so far, done, done on time, late,
    overdue (not handed in after the due date) and the completion rate."""
    moment = now()
    live = qs.exclude(status__in=["cancelled", "excused"])
    due = live.filter(due_at__lte=moment)
    handed_in = Q(status__in=["submitted", "completed"])
    counts = live.aggregate(
        total=Count("pk"),
        submitted=Count("pk", filter=handed_in),
        completed=Count("pk", filter=Q(status="completed")),
        late=Count("pk", filter=handed_in & Q(is_late=True)),
    )
    due_count = due.count()
    done_by_due = due.filter(handed_in).count()
    overdue = due.filter(status__in=HomeworkAssignment.OPEN).count()
    rate = (
        (Decimal(done_by_due) * 100 / Decimal(due_count)).quantize(Decimal("0.1"))
        if due_count
        else None
    )
    return {
        **counts,
        "due": due_count,
        "overdue": overdue,
        "on_time": counts["submitted"] - counts["late"],
        "completion_rate": str(rate) if rate is not None else None,
    }


# --- curriculum and topics ----------------------------------------------------------------------


def curricula(user: Any) -> QuerySet[Curriculum]:
    return scoped(user, Curriculum.objects.all(), "learning.curriculum.view")


def topic_nodes(curriculum_ids: Any = None) -> QuerySet[CurriculumNode]:
    qs = CurriculumNode.objects.filter(curriculum__archived_at__isnull=True).select_related(
        "curriculum", "parent"
    )
    if curriculum_ids is not None:
        qs = qs.filter(curriculum_id__in=curriculum_ids)
    return qs


def topic_suggestions(*, lesson: Any = None, q: str = "", limit: int = 50) -> list[CurriculumNode]:
    """Topics for the lesson report picker: the lesson's subject first, then the rest."""
    qs = topic_nodes().filter(kind=CurriculumNode.Kind.TOPIC)
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__iexact=q) | Q(parent__name__icontains=q))
    subject_id = getattr(getattr(lesson, "service", None), "subject_id", None)
    rows = list(qs[:500])
    rows.sort(
        key=lambda n: (
            0 if subject_id and n.curriculum.subject_id == subject_id else 1,
            n.curriculum.name,
            n.parent.position if n.parent else 0,
            n.position,
        )
    )
    return rows[:limit]


def lesson_topics(user: Any) -> QuerySet[LessonTopic]:
    return scoped(
        user,
        LessonTopic.objects.select_related("node__curriculum", "lesson"),
        "learning.curriculum.view",
    )


def mastery(user: Any) -> QuerySet[TopicMastery]:
    return scoped(
        user, TopicMastery.objects.select_related("node__curriculum"), "learning.curriculum.view"
    )


def coverage(student: Any, curriculum_ids: list[Any] | None = None) -> list[dict[str, Any]]:
    """Per curriculum the student has touched (or ``curriculum_ids``): units with their
    topics, mastery level, times covered and when last covered (the heatmap)."""
    from tutortrack.scheduling.models import LessonAttendee

    lessons = LessonAttendee.objects.filter(student=student).values("lesson_id")
    covered = (
        LessonTopic.objects.filter(lesson_id__in=lessons)
        .values("node_id")
        .annotate(n=Count("lesson_id", distinct=True), last=Max("lesson__start"))
    )
    covered_by_node = {str(r["node_id"]): r for r in covered}
    levels = {
        str(m.node_id): m
        for m in TopicMastery.objects.filter(student=student).only(
            "node_id", "level", "covered_count", "last_covered_at"
        )
    }
    touched = set(
        CurriculumNode.objects.filter(pk__in=[*covered_by_node.keys(), *levels.keys()]).values_list(
            "curriculum_id", flat=True
        )
    )
    ids = set(curriculum_ids or []) | touched
    out = []
    for curriculum in Curriculum.objects.filter(pk__in=ids, archived_at__isnull=True):
        nodes = list(curriculum.nodes.all())
        children: dict[Any, list[CurriculumNode]] = defaultdict(list)
        for node in nodes:
            children[node.parent_id].append(node)
        units: list[dict[str, Any]] = []
        for unit in sorted(children[None], key=lambda n: (n.position, n.name)):
            topics: list[dict[str, Any]] = []
            for topic in sorted(children[unit.pk], key=lambda n: (n.position, n.name)):
                hit = covered_by_node.get(str(topic.pk))
                level = levels.get(str(topic.pk))
                topics.append(
                    {
                        "id": str(topic.pk),
                        "name": topic.name,
                        "code": topic.code,
                        "level": level.level if level else "not_started",
                        "lessons": int(hit["n"]) if hit else 0,
                        "last_covered": hit["last"] if hit else None,
                    }
                )
            units.append({"id": str(unit.pk), "name": unit.name, "topics": topics})
        counted = [t for u in units for t in u["topics"]]
        summary = dict.fromkeys(TopicMastery.RANK, 0)
        for t in counted:
            summary[t["level"]] += 1
        out.append(
            {
                "curriculum": {"id": str(curriculum.pk), "name": curriculum.name},
                "units": units,
                "summary": summary,
                "covered": sum(1 for t in counted if t["lessons"]),
                "topics": len(counted),
            }
        )
    return out


# --- goals and assessments ----------------------------------------------------------------------


def goals(user: Any) -> QuerySet[Goal]:
    return scoped(
        user,
        Goal.objects.select_related("student").prefetch_related("milestones"),
        "learning.goal.view",
    )


def assessments(user: Any) -> QuerySet[Assessment]:
    return scoped(user, Assessment.objects.all(), "learning.assessment.view")


def results(user: Any) -> QuerySet[AssessmentResult]:
    return scoped(
        user,
        AssessmentResult.objects.select_related("assessment", "student"),
        "learning.assessment.view",
    )


def trend(qs: QuerySet[AssessmentResult], subject: Any = None) -> list[dict[str, Any]]:
    """Score trend over time (results with a percentage), oldest first."""
    rows = qs.filter(percent__isnull=False).select_related("assessment__subject")
    if subject:
        rows = rows.filter(assessment__subject_id=subject)
    return [
        {
            "date": r.taken_on,
            "percent": r.percent,
            "grade": r.grade,
            "name": r.assessment.name,
            "kind": r.assessment.kind,
            "subject": r.assessment.subject.name if r.assessment.subject else "",
        }
        for r in rows.order_by("taken_on", "created_at")
    ]


# --- progress reports, library, quizzes ---------------------------------------------------------


def progress_reports(user: Any) -> QuerySet[ProgressReport]:
    return scoped(
        user, ProgressReport.objects.select_related("student", "author"), "learning.progress.view"
    )


def library_items(user: Any) -> QuerySet[LibraryItem]:
    return scoped(user, LibraryItem.objects.all(), "learning.library.view")


def available(item: LibraryItem) -> int:
    out = Loan.objects.filter(item=item, status=Loan.Status.OUT).count()
    lost = Loan.objects.filter(item=item, status=Loan.Status.LOST).count()
    return max(item.quantity - out - lost, 0)


def loans(user: Any) -> QuerySet[Loan]:
    return scoped(user, Loan.objects.select_related("item", "student"), "learning.library.view")


def quizzes(user: Any) -> QuerySet[Quiz]:
    return scoped(user, Quiz.objects.prefetch_related("questions"), "learning.quiz.view")


def quiz_attempts(user: Any) -> QuerySet[QuizAttempt]:
    return scoped(user, QuizAttempt.objects.select_related("quiz", "student"), "learning.quiz.view")


def tutor_tests() -> QuerySet[Quiz]:
    """Live tutor subject tests (E18 FR-18-3, gap batch G5a)."""
    return (
        Quiz.objects.filter(purpose=Quiz.Purpose.TUTOR_TEST, archived_at__isnull=True)
        .select_related("subject", "level")
        .prefetch_related("questions")
    )


def tutor_test_attempts(user_ids: Any) -> QuerySet[QuizAttempt]:
    """Subject-test attempts by these users (newest first)."""
    return QuizAttempt.objects.filter(
        user_id__in=list(user_ids), student__isnull=True, quiz__purpose=Quiz.Purpose.TUTOR_TEST
    ).select_related("quiz", "quiz__subject", "quiz__level")


# --- portal (household) -------------------------------------------------------------------------


def household_shares(household: Any) -> QuerySet[ResourceShare]:
    """Shares reaching the household's students: directly, through their jobs, lessons
    they attend and classes they're enrolled in."""
    from tutortrack.courses.models import Enrolment
    from tutortrack.jobs.models import JobStudent
    from tutortrack.scheduling.models import LessonAttendee

    ids = household.student_ids
    return ResourceShare.objects.filter(
        Q(student_id__in=ids)
        | Q(job_id__in=JobStudent.objects.filter(student_id__in=ids).values("job_id"))
        | Q(lesson_id__in=LessonAttendee.objects.filter(student_id__in=ids).values("lesson_id"))
        | Q(
            group_class_id__in=Enrolment.objects.filter(
                student_id__in=ids, status__in=Enrolment.ATTENDING
            ).values("group_class_id")
        ),
        resource__archived_at__isnull=True,
    )


def household_resources(household: Any) -> QuerySet[Resource]:
    shares = household_shares(household).values("resource_id")
    return Resource.objects.filter(pk__in=shares, archived_at__isnull=True)


def household_assignments(household: Any) -> QuerySet[HomeworkAssignment]:
    return (
        HomeworkAssignment.objects.filter(student_id__in=household.student_ids)
        .exclude(status=HomeworkAssignment.Status.CANCELLED)
        .select_related("homework", "student", "homework__set_by", "homework__quiz")
        .order_by("-due_at")
    )


def household_goals(household: Any) -> QuerySet[Goal]:
    return (
        Goal.objects.filter(student_id__in=household.student_ids, visible_to_family=True)
        .exclude(status=Goal.Status.ABANDONED)
        .select_related("student", "subject")
        .prefetch_related("milestones")
    )


def household_results(household: Any) -> QuerySet[AssessmentResult]:
    return AssessmentResult.objects.filter(
        student_id__in=household.student_ids, visible_to_family=True
    ).select_related("assessment__subject", "student")


def household_reports(household: Any) -> QuerySet[ProgressReport]:
    return ProgressReport.objects.filter(
        student_id__in=household.student_ids, status=ProgressReport.Status.SHARED
    ).select_related("student", "author")


def household_loans(household: Any) -> QuerySet[Loan]:
    return Loan.objects.filter(student_id__in=household.student_ids).select_related(
        "item", "student"
    )


def portal_summary(household: Any) -> dict[str, int]:
    open_homework = household_assignments(household).filter(status__in=HomeworkAssignment.OPEN)
    return {
        "homework_due": open_homework.count(),
        "homework_overdue": open_homework.filter(due_at__lt=now()).count(),
        "resources": household_resources(household).count(),
        "goals": household_goals(household).filter(status=Goal.Status.ACTIVE).count(),
        "reports": household_reports(household).count(),
        "loans": household_loans(household).filter(status=Loan.Status.OUT).count(),
    }


def period_bounds(start: date, end: date) -> tuple[Any, Any]:
    """UTC instants covering local ``start``..``end`` (inclusive) in the org timezone."""
    from datetime import datetime, time, timedelta
    from zoneinfo import ZoneInfo

    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    zone = ZoneInfo(Organisation.objects.get(pk=require_organisation_id()).timezone)
    return (
        datetime.combine(start, time.min, tzinfo=zone),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=zone),
    )
