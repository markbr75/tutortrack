"""Learning writes (E21). Every mutation is audited and publishes its events inside the
transaction. Other apps are reached through their services and selectors: files through
``core.storage`` (plan storage quota, E04), replacement charges through
``billing.services.charge_fee`` (E10), messages through ``comms`` (E13); lesson reports
(E09) are only read, from event handlers.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils.translation import gettext as _

from tutortrack.core import audit
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation, Conflict, NotFound, PermissionDenied
from tutortrack.core.models import StoredFile
from tutortrack.core.money import Money
from tutortrack.core.permissions import permission_scope
from tutortrack.core.time import now
from tutortrack.people.models import Student, TutorProfile
from tutortrack.tenancy.settings_service import get_setting

from . import curricula, events, marking, selectors
from .models import (
    Assessment,
    AssessmentResult,
    Curriculum,
    CurriculumNode,
    Goal,
    GoalMilestone,
    GradeScale,
    Homework,
    HomeworkAssignment,
    HomeworkSubmission,
    LessonTopic,
    LibraryItem,
    Loan,
    ProgressReport,
    Quiz,
    QuizAttempt,
    QuizQuestion,
    Resource,
    ResourceActivity,
    ResourceFolder,
    ResourceShare,
    TopicMastery,
    tutor_students,
)


def _invalid(field_name: str, message: str) -> BusinessRuleViolation:
    return BusinessRuleViolation(message, extra={"errors": {field_name: [message]}})


def _setting(key: str) -> Any:
    return get_setting(f"learning.{key}")


def org_zone() -> ZoneInfo:
    from tutortrack.core.context import require_organisation_id
    from tutortrack.tenancy.models import Organisation

    return ZoneInfo(Organisation.objects.get(pk=require_organisation_id()).timezone)


def org_today() -> date:
    return now().astimezone(org_zone()).date()


def tutor_of(user: Any) -> TutorProfile | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return TutorProfile.objects.filter(membership__user=user).first()


def _own_only(user: Any, codename: str) -> bool:
    return user is not None and permission_scope(user, codename) == "own"


def _check_students(user: Any, codename: str, students: Iterable[Student]) -> None:
    """Tutors (own scope) may only act for their own students."""
    if not _own_only(user, codename):
        return
    mine = {str(pk) for pk in tutor_students(user).values_list("pk", flat=True)}
    if any(str(s.pk) not in mine for s in students):
        raise PermissionDenied(_("You can only do this for your own students."))


def _save(instance: Any, created: bool, fields: dict[str, Any], keys: Iterable[str]) -> None:
    """Set ``keys`` present in ``fields`` and save, auditing a diff (or the creation)."""
    if created:
        for key in keys:
            if key in fields:
                setattr(instance, key, fields[key])
        instance.save()
        audit.record_create(instance)
        return
    with audit.track(instance):
        for key in keys:
            if key in fields:
                setattr(instance, key, fields[key])
        instance.save()


# --- resources (T01) ----------------------------------------------------------------------------

YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
GOOGLE_HOSTS = {"docs.google.com", "drive.google.com", "slides.google.com", "sheets.google.com"}


def media_type_for(kind: str, content_type: str = "", url: str = "") -> str:
    if kind == Resource.Kind.LINK:
        host = (urlparse(url).hostname or "").lower()
        if host in YOUTUBE_HOSTS:
            return Resource.MediaType.YOUTUBE
        if host in GOOGLE_HOSTS:
            return Resource.MediaType.GOOGLE_DOCS
        return Resource.MediaType.LINK
    if content_type == "application/pdf":
        return Resource.MediaType.PDF
    for prefix, media in (("image/", "image"), ("audio/", "audio"), ("video/", "video")):
        if content_type.startswith(prefix):
            return media
    return Resource.MediaType.DOCUMENT


def _clean_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise _invalid("url", _("Enter a web address starting with https://."))
    return url


@transaction.atomic
def save_folder(folder: ResourceFolder | None, *, user: Any = None, **data: Any) -> ResourceFolder:
    created = folder is None
    folder = folder or ResourceFolder()
    if created and _own_only(user, "learning.resource.manage"):
        data["owner"] = tutor_of(user)
    elif (
        not created
        and _own_only(user, "learning.resource.manage")
        and (folder.owner is None or folder.owner != tutor_of(user))
    ):
        raise PermissionDenied(_("You can only change your own folders."))
    parent = data.get("parent", folder.parent if not created else None)
    if parent is not None:
        node: ResourceFolder | None = parent
        while node is not None:
            if not created and node.pk == folder.pk:
                raise _invalid("parent", _("A folder can't be inside itself."))
            node = node.parent
    _save(folder, created, data, ("name", "parent", "owner"))
    return folder


@transaction.atomic
def delete_folder(folder: ResourceFolder, *, user: Any = None) -> None:
    if _own_only(user, "learning.resource.manage") and folder.owner != tutor_of(user):
        raise PermissionDenied(_("You can only change your own folders."))
    Resource.objects.filter(folder=folder).update(folder=folder.parent)
    ResourceFolder.objects.filter(parent=folder).update(parent=folder.parent)
    audit.record(folder, "delete", {"name": [folder.name, None]})
    folder.delete()


def _check_resource_owner(resource: Resource, user: Any) -> None:
    if _own_only(user, "learning.resource.manage"):
        tutor = tutor_of(user)
        if tutor is None or resource.owner_id != tutor.pk:
            raise PermissionDenied(_("You can only change your own resources."))


@transaction.atomic
def save_resource(resource: Resource | None, *, user: Any = None, **data: Any) -> Resource:
    """Create or change a resource: an uploaded file (counted against the plan's storage)
    or a link (YouTube, Google Docs or any web page)."""
    from tutortrack.core.storage import services as storage

    created = resource is None
    resource = resource or Resource()
    if created:
        if _own_only(user, "learning.resource.manage"):
            data["owner"] = tutor_of(user)
            if data["owner"] is None:
                raise PermissionDenied(_("There's no tutor profile for this login."))
    else:
        _check_resource_owner(resource, user)
        data.pop("owner", None)
    topics = data.pop("topics", None)
    kind = data.get("kind", resource.kind or Resource.Kind.LINK)
    data["kind"] = kind
    if kind == Resource.Kind.FILE:
        stored: StoredFile | None = data.get("file", resource.file if not created else None)
        if stored is None:
            raise _invalid("file", _("Upload a file."))
        if stored.status == StoredFile.Status.REJECTED:
            raise _invalid("file", _("This upload was rejected."))
        data["url"] = ""
        data["media_type"] = media_type_for(kind, stored.content_type)
    else:
        data["url"] = _clean_url(data.get("url", resource.url))
        data["file"] = None
        data["media_type"] = media_type_for(kind, url=data["url"])
    tags = data.get("tags")
    if tags is not None:
        data["tags"] = sorted({str(t).strip()[:40] for t in tags if str(t).strip()})[:20]
    if data.get("owner") is not None and data.get("visibility") is None and created:
        data["visibility"] = Resource.Visibility.PRIVATE
    _save(
        resource,
        created,
        data,
        (
            "title",
            "description",
            "kind",
            "file",
            "url",
            "media_type",
            "folder",
            "owner",
            "subject",
            "level",
            "tags",
            "visibility",
        ),
    )
    if topics is not None:
        resource.topics.set(topics)
    if resource.file is not None:
        storage.attach(resource.file, resource)
    return resource


@transaction.atomic
def set_resource_archived(resource: Resource, archived: bool, *, user: Any = None) -> Resource:
    _check_resource_owner(resource, user)
    with audit.track(resource, "archive" if archived else "unarchive"):
        resource.archived_at = now() if archived else None
        resource.save(update_fields=["archived_at", "updated_at"])
    return resource


def _share_students(target: str, obj: Any) -> list[str]:
    from tutortrack.courses.models import Enrolment
    from tutortrack.jobs.models import JobStudent
    from tutortrack.scheduling.models import LessonAttendee

    if target == "student":
        ids = [obj.pk]
    elif target == "job":
        ids = list(JobStudent.objects.filter(job=obj).values_list("student_id", flat=True))
    elif target == "lesson":
        ids = list(LessonAttendee.objects.filter(lesson=obj).values_list("student_id", flat=True))
    else:
        ids = list(
            Enrolment.objects.filter(group_class=obj, status__in=Enrolment.ATTENDING).values_list(
                "student_id", flat=True
            )
        )
    return [str(i) for i in ids]


@transaction.atomic
def share_resource(
    resource: Resource,
    *,
    user: Any = None,
    students: Iterable[Any] = (),
    jobs: Iterable[Any] = (),
    lessons: Iterable[Any] = (),
    classes: Iterable[Any] = (),
    message: str = "",
) -> list[ResourceShare]:
    """Share with students, every student of a job, a lesson's attendees or a class
    (E20). Already-shared targets are kept; families see the resource in the portal."""
    if resource.archived_at is not None:
        raise Conflict(_("Archived resources can't be shared."))
    targets = [
        *(("student", s) for s in students),
        *(("job", j) for j in jobs),
        *(("lesson", ls) for ls in lessons),
        *(("group_class", c) for c in classes),
    ]
    if not targets:
        raise _invalid("students", _("Choose who to share it with."))
    if _own_only(user, "learning.resource.share"):
        allowed = {str(pk) for pk in tutor_students(user).values_list("pk", flat=True)}
        for target, obj in targets:
            ids = _share_students(target, obj)
            if not ids or any(i not in allowed for i in ids):
                raise PermissionDenied(_("You can only share with your own students."))
    out = []
    for target, obj in targets:
        existing = ResourceShare.objects.filter(resource=resource, **{target: obj}).first()
        if existing is not None:
            out.append(existing)
            continue
        share = ResourceShare.objects.create(
            resource=resource,
            message=message[:500],
            shared_by=user if getattr(user, "is_authenticated", False) else None,
            **{target: obj},
        )
        audit.record(resource, "share", {"target": [None, f"{target}:{obj.pk}"]})
        publish(
            events.ResourceShared(
                subject_id=resource.pk,
                share_id=str(share.pk),
                target=target,
                target_id=str(obj.pk),
                student_ids=_share_students(target, obj),
            )
        )
        out.append(share)
    return out


@transaction.atomic
def unshare(share: ResourceShare, *, user: Any = None) -> None:
    if _own_only(user, "learning.resource.share") and share.shared_by_id != getattr(
        user, "pk", None
    ):
        raise PermissionDenied(_("You can only remove your own shares."))
    target, value = share.target
    audit.record(share.resource, "unshare", {"target": [f"{target}:{value}", None]})
    share.delete()


@transaction.atomic
def record_open(resource: Resource, user: Any, *, student: Any = None, download: bool) -> None:
    """Track that ``user`` viewed or downloaded a shared resource (FR-21-1)."""
    moment = now()
    activity, _created = ResourceActivity.objects.select_for_update().get_or_create(
        resource=resource,
        user=user,
        defaults={"student": student, "first_opened_at": moment, "last_opened_at": moment},
    )
    if download:
        activity.downloads += 1
    else:
        activity.views += 1
    activity.last_opened_at = moment
    if student is not None and activity.student_id is None:
        activity.student = student
    activity.save()


def open_resource(resource: Resource, user: Any, *, student: Any = None) -> dict[str, Any]:
    """Where to send the viewer: a short-lived download link for files, the link itself
    otherwise. Records the view."""
    from tutortrack.core.storage import services as storage

    if resource.kind == Resource.Kind.FILE and resource.file is not None:
        url, expires = storage.download_url(user, resource.file)
        record_open(resource, user, student=student, download=True)
        return {"url": url, "expires_in": expires, "kind": resource.kind}
    record_open(resource, user, student=student, download=False)
    return {"url": resource.url, "expires_in": None, "kind": resource.kind}


def lesson_shares(lesson: Any, student_ids: list[str] | None = None) -> Any:
    """Shares that put resources in a lesson's classroom (FR-21-8): the lesson's own, its
    job's, and (for a family) their students'."""
    query = Q(lesson=lesson)
    if lesson.job_id:
        query |= Q(job_id=lesson.job_id)
    if student_ids:
        query |= Q(student_id__in=student_ids)
    return (
        ResourceShare.objects.filter(query, resource__archived_at__isnull=True)
        .select_related("resource")
        .order_by("-created_at")
    )


@transaction.atomic
def open_lesson_resource(
    lesson: Any, resource_id: Any, user: Any, *, student_ids: list[str] | None = None
) -> dict[str, Any]:
    """Open a resource from the lesson's classroom (gap G5c, FR-21-8). The caller has
    checked the viewer belongs in the classroom; the resource must be shared into it, so
    a tutor can open what staff shared with the lesson even from the staff library."""
    from tutortrack.core.storage import services as storage

    share = lesson_shares(lesson, student_ids).filter(resource_id=resource_id).first()
    if share is None:
        raise NotFound()
    resource = share.resource
    student = None
    if student_ids:
        student = Student.objects.filter(pk=student_ids[0]).first()
    if resource.kind == Resource.Kind.FILE and resource.file is not None:
        url, expires = storage.presign_download(resource.file, inline=True)
        record_open(resource, user, student=student, download=True)
        return {"url": url, "expires_in": expires, "kind": resource.kind}
    record_open(resource, user, student=student, download=False)
    return {"url": resource.url, "expires_in": None, "kind": resource.kind}


# --- grade scales -------------------------------------------------------------------------------


@transaction.atomic
def ensure_default_scales() -> GradeScale:
    """The organisation's grade scales (percentage, letters, 9-1, custom) on first use."""
    existing = GradeScale.objects.filter(is_default=True, archived_at__isnull=True).first()
    if existing is not None:
        return existing
    if GradeScale.objects.exists():
        first = GradeScale.objects.filter(archived_at__isnull=True).order_by("created_at").first()
        if first is not None:
            first.is_default = True
            first.save(update_fields=["is_default", "updated_at"])
            return first
    scales = [
        GradeScale.objects.create(name=name, kind=kind, grades=grades, is_default=i == 0)
        for i, (name, kind, grades) in enumerate(marking.DEFAULT_SCALES)
    ]
    return scales[0]


def _clean_grades(kind: str, grades: Any) -> list[str]:
    if kind == GradeScale.Kind.PERCENT:
        return []
    cleaned = [str(g).strip()[:20] for g in (grades or []) if str(g).strip()]
    if not 2 <= len(cleaned) <= 30 or len(set(cleaned)) != len(cleaned):
        raise _invalid("grades", _("List between 2 and 30 different grades, best first."))
    return cleaned


@transaction.atomic
def save_grade_scale(scale: GradeScale | None, **data: Any) -> GradeScale:
    created = scale is None
    scale = scale or GradeScale()
    kind = data.get("kind", scale.kind)
    if "grades" in data or created:
        data["grades"] = _clean_grades(kind, data.get("grades", scale.grades))
    if data.get("is_default"):
        GradeScale.objects.exclude(pk=scale.pk).filter(is_default=True).update(is_default=False)
    _save(scale, created, data, ("name", "kind", "grades", "is_default"))
    return scale


def scale_for(homework: Homework) -> GradeScale:
    return homework.grade_scale or ensure_default_scales()


# --- homework (T02) -----------------------------------------------------------------------------


def _homework_students(
    students: Iterable[Student], group_class: Any, job: Any, lesson: Any
) -> list[Student]:
    from tutortrack.courses.models import Enrolment
    from tutortrack.jobs.models import JobStudent
    from tutortrack.scheduling.models import LessonAttendee

    chosen: dict[str, Student] = {str(s.pk): s for s in students}
    extra: list[Any] = []
    if group_class is not None:
        extra += Enrolment.objects.filter(
            group_class=group_class, status__in=Enrolment.ATTENDING
        ).values_list("student_id", flat=True)
    if job is not None:
        extra += JobStudent.objects.filter(job=job).values_list("student_id", flat=True)
    if lesson is not None and not chosen and group_class is None and job is None:
        extra += LessonAttendee.objects.filter(lesson=lesson).values_list("student_id", flat=True)
    for student in Student.objects.filter(pk__in=extra, archived_at__isnull=True):
        chosen.setdefault(str(student.pk), student)
    return list(chosen.values())


def _publish_assigned(assignment: HomeworkAssignment) -> None:
    publish(
        events.HomeworkAssigned(
            subject_id=assignment.pk,
            homework_id=str(assignment.homework_id),
            student_id=str(assignment.student_id),
            round=assignment.round,
            title=assignment.homework.title,
            due_at=assignment.due_at.isoformat(),
        ),
        branch_id=assignment.branch_id,
    )


@transaction.atomic
def assign_homework(
    *,
    user: Any = None,
    title: str,
    due_at: datetime,
    students: Iterable[Student] = (),
    group_class: Any = None,
    job: Any = None,
    lesson: Any = None,
    lesson_report: Any = None,
    set_by: TutorProfile | None = None,
    resources: Iterable[Resource] = (),
    attachments: Iterable[StoredFile] = (),
    **data: Any,
) -> Homework:
    """Set homework for students (picked, a class's roster, a job's students or a lesson's
    attendees). Each student gets an assignment; ``homework.assigned`` starts its
    reminder workflow."""
    from tutortrack.core.storage import services as storage

    chosen = _homework_students(students, group_class, job, lesson)
    if not chosen:
        raise _invalid("students", _("Choose at least one student."))
    if due_at <= now():
        raise _invalid("due_at", _("The due date must be in the future."))
    _check_students(user, "learning.homework.manage", chosen)
    submission_type = data.get("submission_type", Homework.SubmissionType.TEXT)
    quiz = data.get("quiz")
    if submission_type == Homework.SubmissionType.QUIZ and quiz is None:
        raise _invalid("quiz", _("Choose the quiz to set."))
    if quiz is not None:
        if not quiz.questions.exists():
            raise _invalid("quiz", _("The quiz has no questions yet."))
        data["submission_type"] = Homework.SubmissionType.QUIZ
    homework = Homework(
        title=title,
        due_at=due_at,
        group_class=group_class,
        job=job,
        lesson=lesson,
        lesson_report=lesson_report,
        set_by=set_by or tutor_of(user),
        **{
            k: v
            for k, v in data.items()
            if k in {"instructions", "expected_minutes", "submission_type", "grade_scale", "quiz"}
        },
    )
    homework.save()
    audit.record_create(homework)
    homework.resources.set(list(resources))
    files = list(attachments)
    homework.attachments.set(files)
    for stored in files:
        storage.attach(stored, homework)
    moment = now()
    for student in chosen:
        assignment = HomeworkAssignment.objects.create(
            homework=homework,
            student=student,
            branch_id=student.branch_id,
            due_at=due_at,
            round_started_at=moment,
        )
        _publish_assigned(assignment)
    return homework


def _signal(assignment: HomeworkAssignment) -> None:
    from tutortrack.core.workflows import signal

    from .processes import homework_workflow_id

    signal(
        homework_workflow_id(assignment.organisation_id, assignment.pk, assignment.round),
        "changed",
    )


@transaction.atomic
def update_homework(homework: Homework, *, user: Any = None, **data: Any) -> Homework:
    if homework.status == Homework.Status.CANCELLED:
        raise Conflict(_("This homework was cancelled."))
    _check_students(
        user,
        "learning.homework.manage",
        [a.student for a in homework.assignments.select_related("student")],
    )
    old_due = homework.due_at
    resources = data.pop("resources", None)
    with audit.track(homework):
        for key in ("title", "instructions", "due_at", "expected_minutes", "grade_scale"):
            if key in data:
                setattr(homework, key, data[key])
        homework.save()
    if resources is not None:
        homework.resources.set(resources)
    if homework.due_at != old_due:
        if homework.due_at <= now():
            raise _invalid("due_at", _("The due date must be in the future."))
        for assignment in homework.assignments.filter(
            status__in=HomeworkAssignment.OPEN, due_at=old_due
        ):
            assignment.due_at = homework.due_at
            assignment.overdue_at = None
            assignment.reminded_at = None
            assignment.save(update_fields=["due_at", "overdue_at", "reminded_at", "updated_at"])
            _signal(assignment)
    return homework


@transaction.atomic
def cancel_homework(homework: Homework, *, user: Any = None) -> Homework:
    if homework.status == Homework.Status.CANCELLED:
        return homework
    with audit.track(homework, "cancel"):
        homework.status = Homework.Status.CANCELLED
        homework.save(update_fields=["status", "updated_at"])
    live = homework.assignments.exclude(
        status__in=[HomeworkAssignment.Status.COMPLETED, HomeworkAssignment.Status.EXCUSED]
    )
    count = 0
    for assignment in live:
        assignment.status = HomeworkAssignment.Status.CANCELLED
        assignment.save(update_fields=["status", "updated_at"])
        _signal(assignment)
        count += 1
    publish(events.HomeworkCancelled(subject_id=homework.pk, assignments=count))
    return homework


@transaction.atomic
def submit_homework(
    assignment: HomeworkAssignment,
    *,
    user: Any = None,
    body: str = "",
    link: str = "",
    files: Iterable[StoredFile] = (),
    quiz_answers: dict[str, Any] | None = None,
) -> HomeworkSubmission:
    """A student (or parent) hands homework in; late work is accepted and marked late
    unless the organisation turned that off. Quizzes are marked at once."""
    from tutortrack.core.storage import services as storage

    assignment = HomeworkAssignment.objects.select_for_update().get(pk=assignment.pk)
    homework = assignment.homework
    if homework.status == Homework.Status.CANCELLED or not assignment.is_open:
        raise Conflict(_("This homework can't be handed in now."))
    moment = now()
    late = moment > assignment.due_at
    if late and not _setting("late_submissions"):
        raise Conflict(_("The due date has passed."))
    kind = homework.submission_type
    files = list(files)
    body = (body or "").strip()
    if kind == Homework.SubmissionType.TEXT and not body:
        raise _invalid("body", _("Write your answer."))
    if kind == Homework.SubmissionType.LINK or link:
        link = _clean_url(link)
    if kind == Homework.SubmissionType.FILE and not files:
        raise _invalid("files", _("Upload your work."))
    attempt_row: QuizAttempt | None = None
    if kind == Homework.SubmissionType.QUIZ:
        if quiz_answers is None or homework.quiz is None:
            raise _invalid("quiz_answers", _("Answer the quiz questions."))
        attempt_row = take_quiz(
            homework.quiz,
            answers=quiz_answers,
            student=assignment.student,
            user=user,
            assignment=assignment,
        )
    submission = HomeworkSubmission.objects.create(
        assignment=assignment,
        attempt=assignment.submissions.count() + 1,
        body=body[:20000],
        link=link,
        quiz_attempt=attempt_row,
        submitted_by=user if getattr(user, "is_authenticated", False) else None,
        is_late=late,
    )
    if files:
        submission.files.set(files)
        for stored in files:
            storage.attach(stored, submission)
    with audit.track(assignment, "submit"):
        assignment.status = HomeworkAssignment.Status.SUBMITTED
        assignment.submitted_at = moment
        assignment.is_late = late
        assignment.save()
    publish(
        events.HomeworkSubmitted(
            subject_id=assignment.pk,
            homework_id=str(homework.pk),
            student_id=str(assignment.student_id),
            round=assignment.round,
            is_late=late,
        ),
        branch_id=assignment.branch_id,
    )
    if attempt_row is not None:
        _complete(
            assignment,
            grade=f"{attempt_row.percent.normalize():f}%",
            score_percent=attempt_row.percent,
            feedback="",
            user=None,
        )
    return submission


def _complete(
    assignment: HomeworkAssignment,
    *,
    grade: str,
    score_percent: Decimal | None,
    feedback: str,
    user: Any,
) -> None:
    moment = now()
    with audit.track(assignment, "grade"):
        assignment.status = HomeworkAssignment.Status.COMPLETED
        assignment.completed_at = moment
        assignment.grade = grade
        assignment.score_percent = score_percent
        assignment.feedback = feedback
        assignment.reviewed_at = moment
        assignment.reviewed_by = user if getattr(user, "is_authenticated", False) else None
        assignment.save()
    publish(
        events.HomeworkGraded(
            subject_id=assignment.pk,
            homework_id=str(assignment.homework_id),
            student_id=str(assignment.student_id),
            round=assignment.round,
            grade=grade,
            score_percent=str(score_percent) if score_percent is not None else None,
        ),
        branch_id=assignment.branch_id,
    )


@transaction.atomic
def review_homework(
    assignment: HomeworkAssignment,
    *,
    user: Any = None,
    outcome: str,
    grade: str = "",
    feedback: str = "",
    due_at: datetime | None = None,
) -> HomeworkAssignment:
    """Tutor review: ``complete`` (grade on the homework's scale and feedback) or
    ``resubmit`` (back to the student with a new due date: a new reminder round)."""
    assignment = HomeworkAssignment.objects.select_for_update().get(pk=assignment.pk)
    _check_students(user, "learning.homework.review", [assignment.student])
    if assignment.status in {
        HomeworkAssignment.Status.CANCELLED,
        HomeworkAssignment.Status.EXCUSED,
        HomeworkAssignment.Status.COMPLETED,
    }:
        raise Conflict(_("This homework has already been closed."))
    feedback = (feedback or "").strip()[:10000]
    if outcome == "complete":
        scale = scale_for(assignment.homework)
        clean = marking.check_grade(scale.kind, scale.grades, grade)
        pct = (
            Decimal(clean.rstrip("%")).quantize(marking.TWO_PLACES)
            if scale.kind == "percent" and clean
            else None
        )
        _complete(assignment, grade=clean, score_percent=pct, feedback=feedback, user=user)
        return assignment
    if outcome != "resubmit":
        raise _invalid("outcome", _("Choose complete or resubmit."))
    if assignment.status != HomeworkAssignment.Status.SUBMITTED:
        raise Conflict(_("Only handed-in work can be returned."))
    new_due = due_at or now() + timedelta(days=3)
    if new_due <= now():
        raise _invalid("due_at", _("The due date must be in the future."))
    with audit.track(assignment, "return"):
        assignment.status = HomeworkAssignment.Status.RETURNED
        assignment.feedback = feedback
        assignment.round += 1
        assignment.round_started_at = now()
        assignment.due_at = new_due
        assignment.reminded_at = None
        assignment.overdue_at = None
        assignment.reviewed_at = now()
        assignment.reviewed_by = user if getattr(user, "is_authenticated", False) else None
        assignment.save()
    publish(
        events.HomeworkReturned(
            subject_id=assignment.pk,
            homework_id=str(assignment.homework_id),
            student_id=str(assignment.student_id),
            round=assignment.round,
            due_at=new_due.isoformat(),
        ),
        branch_id=assignment.branch_id,
    )
    return assignment


@transaction.atomic
def excuse_homework(assignment: HomeworkAssignment, *, user: Any = None) -> HomeworkAssignment:
    _check_students(user, "learning.homework.review", [assignment.student])
    if assignment.status in {HomeworkAssignment.Status.COMPLETED, "cancelled"}:
        raise Conflict(_("This homework has already been closed."))
    with audit.track(assignment, "excuse"):
        assignment.status = HomeworkAssignment.Status.EXCUSED
        assignment.save(update_fields=["status", "updated_at"])
    _signal(assignment)
    return assignment


def homework_from_report(report_id: Any) -> Homework | None:
    """``learning.homework_from_reports``: homework written in a lesson report (E09
    ``homework`` field) is set for the lesson's students. Once per report."""
    from tutortrack.delivery.models import LessonReport

    if not _setting("homework_from_reports"):
        return None
    report = (
        LessonReport.objects.select_related("lesson", "tutor", "template_version")
        .filter(pk=report_id)
        .first()
    )
    if report is None or Homework.objects.filter(lesson_report=report).exists():
        return None
    texts = [
        str(report.answers.get(f["key"], "")).strip()
        for f in report.template_version.fields
        if f.get("type") == "homework"
    ]
    text = "\n\n".join(t for t in texts if t)
    if not text:
        return None
    zone = org_zone()
    due_day = now().astimezone(zone).date() + timedelta(
        days=int(_setting("homework_report_due_days"))
    )
    due_at = datetime.combine(due_day, datetime.min.time().replace(hour=18), tzinfo=zone)
    with transaction.atomic():
        return assign_homework(
            title=_("Homework: %(lesson)s") % {"lesson": report.lesson.title},
            instructions=text,
            due_at=due_at,
            lesson=report.lesson,
            lesson_report=report,
            set_by=report.tutor,
            submission_type=Homework.SubmissionType.NONE,
        )


# --- homework workflow steps (E21-TW1) ----------------------------------------------------------


def assignment_state(assignment_id: Any) -> dict[str, Any]:
    assignment = HomeworkAssignment.objects.select_related("homework").get(pk=assignment_id)
    hours = int(_setting("homework_reminder_hours"))
    remind_at = assignment.due_at - timedelta(hours=hours)
    started = assignment.round_started_at or assignment.created_at
    return {
        "status": assignment.status,
        "open": assignment.is_open and assignment.homework.status == Homework.Status.ACTIVE,
        "round": assignment.round,
        "due_at": assignment.due_at.isoformat(),
        "remind_at": remind_at.isoformat(),
        "remind": bool(hours) and assignment.reminded_at is None and remind_at > started,
        "overdue": assignment.overdue_at is not None,
    }


@transaction.atomic
def send_homework_reminder(assignment_id: Any) -> bool:
    from tutortrack.comms import services as comms

    assignment = HomeworkAssignment.objects.select_for_update().get(pk=assignment_id)
    if not assignment.is_open or assignment.reminded_at is not None:
        return False
    assignment.reminded_at = now()
    assignment.save(update_fields=["reminded_at", "updated_at"])
    comms.notify(
        "homework_reminder", assignment, key=f"homework-reminder:{assignment.pk}:{assignment.round}"
    )
    return True


@transaction.atomic
def mark_homework_overdue(assignment_id: Any, *, dedupe_key: str | None = None) -> str:
    from tutortrack.comms import services as comms

    assignment = HomeworkAssignment.objects.select_for_update().get(pk=assignment_id)
    if not assignment.is_open:
        return str(assignment.status)
    if assignment.overdue_at is None:
        assignment.overdue_at = now()
        assignment.save(update_fields=["overdue_at", "updated_at"])
        publish(
            events.HomeworkOverdue(
                subject_id=assignment.pk,
                homework_id=str(assignment.homework_id),
                student_id=str(assignment.student_id),
                round=assignment.round,
                due_at=assignment.due_at.isoformat(),
            ),
            branch_id=assignment.branch_id,
            dedupe_key=dedupe_key,
        )
        comms.notify(
            "homework_overdue",
            assignment,
            key=f"homework-overdue:{assignment.pk}:{assignment.round}",
        )
    return "overdue"


# --- curriculum and topics (T03) ----------------------------------------------------------------


@transaction.atomic
def save_curriculum(curriculum: Curriculum | None, **data: Any) -> Curriculum:
    created = curriculum is None
    curriculum = curriculum or Curriculum()
    _save(curriculum, created, data, ("name", "subject", "level", "exam_board", "description"))
    return curriculum


@transaction.atomic
def set_curriculum_archived(curriculum: Curriculum, archived: bool) -> Curriculum:
    with audit.track(curriculum, "archive" if archived else "unarchive"):
        curriculum.archived_at = now() if archived else None
        curriculum.save(update_fields=["archived_at", "updated_at"])
    return curriculum


def _next_position(curriculum: Curriculum, parent: CurriculumNode | None) -> int:
    last = (
        CurriculumNode.objects.filter(curriculum=curriculum, parent=parent)
        .order_by("-position")
        .values_list("position", flat=True)
        .first()
    )
    return (last or 0) + 1


@transaction.atomic
def save_node(node: CurriculumNode | None, **data: Any) -> CurriculumNode:
    """Units sit at the top of a curriculum; topics sit in a unit."""
    created = node is None
    node = node or CurriculumNode()
    curriculum = data.get("curriculum", node.curriculum if not created else None)
    parent = data.get("parent", node.parent if not created else None)
    kind = data.get("kind", node.kind if not created else CurriculumNode.Kind.TOPIC)
    if curriculum is None:
        raise _invalid("curriculum", _("Choose a curriculum."))
    if kind == CurriculumNode.Kind.UNIT and parent is not None:
        raise _invalid("parent", _("Units sit at the top of the curriculum."))
    if kind == CurriculumNode.Kind.TOPIC:
        if parent is None or parent.kind != CurriculumNode.Kind.UNIT:
            raise _invalid("parent", _("Put the topic in a unit."))
        if parent.curriculum_id != curriculum.pk:
            raise _invalid("parent", _("The unit belongs to another curriculum."))
    code = str(data.get("code", node.code if not created else "")).strip()
    if code and (
        CurriculumNode.objects.filter(curriculum=curriculum, code=code).exclude(pk=node.pk).exists()
    ):
        raise _invalid("code", _("Another topic already uses this code."))
    data.update({"curriculum": curriculum, "parent": parent, "kind": kind, "code": code})
    if created and "position" not in data:
        data["position"] = _next_position(curriculum, parent)
    _save(node, created, data, ("curriculum", "parent", "kind", "name", "code", "position"))
    return node


@transaction.atomic
def delete_node(node: CurriculumNode) -> None:
    ids = [node.pk, *node.children.values_list("pk", flat=True)]
    if LessonTopic.objects.filter(node_id__in=ids).exists():
        raise Conflict(_("Lessons already cover this; rename it instead."))
    audit.record(node, "delete", {"name": [node.name, None]})
    node.delete()


@transaction.atomic
def install_builtin(key: str, *, subject: Any = None, level: Any = None) -> Curriculum:
    spec = curricula.BUILTINS.get(key)
    if spec is None:
        raise _invalid("key", _("Unknown curriculum."))
    if Curriculum.objects.filter(source_key=key, archived_at__isnull=True).exists():
        raise Conflict(_("This curriculum is already installed."))
    curriculum = save_curriculum(
        None,
        name=spec.name,
        subject=subject,
        level=level,
        exam_board=spec.exam_board,
        description=_("Based on the %(name)s specification.") % {"name": spec.name},
    )
    curriculum.source_key = key
    curriculum.save(update_fields=["source_key", "updated_at"])
    for u, (code, unit_name, topics) in enumerate(curricula.builtin_codes(spec), start=1):
        unit = CurriculumNode.objects.create(
            curriculum=curriculum, kind="unit", name=unit_name, code=code, position=u
        )
        CurriculumNode.objects.bulk_create(
            [
                CurriculumNode(
                    organisation_id=curriculum.organisation_id,
                    curriculum=curriculum,
                    parent=unit,
                    kind="topic",
                    name=name,
                    code=topic_code,
                    position=t,
                )
                for t, (topic_code, name) in enumerate(topics, start=1)
            ]
        )
    return curriculum


@transaction.atomic
def import_csv(curriculum: Curriculum, text: str) -> dict[str, int]:
    """Add units and topics from a CSV (``unit,topic,code``). Existing units are matched
    by name, existing topics by code or name, so re-importing adds only what's new."""
    parsed = curricula.parse_csv(text)
    nodes = list(curriculum.nodes.all())
    units = {n.name.casefold(): n for n in nodes if n.kind == "unit"}
    codes = {n.code for n in nodes if n.code}
    names = {(n.parent_id, n.name.casefold()) for n in nodes if n.kind == "topic"}
    added_units = added_topics = skipped = 0
    for row in parsed:
        unit = units.get(row.name.casefold())
        if unit is None:
            if row.code and row.code in codes:
                raise _invalid("file", _("The code %(code)s is already used.") % {"code": row.code})
            unit = CurriculumNode.objects.create(
                curriculum=curriculum,
                kind="unit",
                name=row.name,
                code=row.code,
                position=_next_position(curriculum, None),
            )
            units[row.name.casefold()] = unit
            codes.add(row.code)
            added_units += 1
        for name, code in row.topics:
            if (code and code in codes) or (unit.pk, name.casefold()) in names:
                skipped += 1
                continue
            CurriculumNode.objects.create(
                curriculum=curriculum,
                parent=unit,
                kind="topic",
                name=name,
                code=code,
                position=_next_position(curriculum, unit),
            )
            names.add((unit.pk, name.casefold()))
            if code:
                codes.add(code)
            added_topics += 1
    result = {"units": added_units, "topics": added_topics, "skipped": skipped}
    audit.record(curriculum, "import", {"import": [None, result]})
    return result


def _bump_mastery(student: Student, node: CurriculumNode, when: datetime, user: Any) -> None:
    row, created = TopicMastery.objects.get_or_create(
        student=student, node=node, defaults={"branch_id": student.branch_id}
    )
    previous = row.level
    row.covered_count += 1
    row.last_covered_at = max(filter(None, [row.last_covered_at, when]))
    if row.level == TopicMastery.Level.NOT_STARTED:
        row.level = TopicMastery.Level.LEARNING
    row.updated_by_user = user if getattr(user, "is_authenticated", False) else None
    row.save()
    if row.level != previous or created:
        publish(
            events.TopicMasteryChanged(
                subject_id=row.pk,
                student_id=str(student.pk),
                node_id=str(node.pk),
                level=row.level,
                previous=previous if not created else TopicMastery.Level.NOT_STARTED,
            ),
            branch_id=row.branch_id,
        )


@transaction.atomic
def tag_lesson(
    lesson: Any, nodes: Iterable[CurriculumNode], *, user: Any = None, report: Any = None
) -> list[LessonTopic]:
    """Record topics covered in a lesson (FR-21-3): each lesson student's mastery moves
    to at least *learning* and counts the coverage."""
    from tutortrack.scheduling.models import LessonAttendee

    students = [
        a.student for a in LessonAttendee.objects.filter(lesson=lesson).select_related("student")
    ]
    if (
        _own_only(user, "learning.mastery.edit")
        and not lesson.tutors.filter(tutor__membership__user=user).exists()
    ):
        raise PermissionDenied(_("You can only tag your own lessons."))
    created = []
    for node in nodes:
        if node.kind != CurriculumNode.Kind.TOPIC:
            raise _invalid("nodes", _("Choose topics, not units."))
        row, is_new = LessonTopic.objects.get_or_create(
            lesson=lesson,
            node=node,
            defaults={
                "report": report,
                "tagged_by": user if getattr(user, "is_authenticated", False) else None,
            },
        )
        if not is_new:
            continue
        audit.record(
            row, "create", {"node": [None, str(node.pk)], "lesson": [None, str(lesson.pk)]}
        )
        for student in students:
            _bump_mastery(student, node, lesson.start, user)
        created.append(row)
    return created


@transaction.atomic
def untag_lesson(row: LessonTopic, *, user: Any = None) -> None:
    from tutortrack.scheduling.models import LessonAttendee

    if (
        _own_only(user, "learning.mastery.edit")
        and not row.lesson.tutors.filter(tutor__membership__user=user).exists()
    ):
        raise PermissionDenied(_("You can only tag your own lessons."))
    students = LessonAttendee.objects.filter(lesson=row.lesson).values("student_id")
    for mastery in TopicMastery.objects.filter(node=row.node, student_id__in=students):
        mastery.covered_count = max(mastery.covered_count - 1, 0)
        mastery.save(update_fields=["covered_count", "updated_at"])
    audit.record(row, "delete", {"node": [str(row.node_id), None]})
    row.delete()


@transaction.atomic
def set_mastery(
    student: Student,
    node: CurriculumNode,
    level: str,
    *,
    user: Any = None,
    notes: str | None = None,
) -> TopicMastery:
    if level not in TopicMastery.RANK:
        raise _invalid("level", _("Unknown mastery level."))
    if node.kind != CurriculumNode.Kind.TOPIC:
        raise _invalid("node", _("Choose a topic, not a unit."))
    _check_students(user, "learning.mastery.edit", [student])
    row, created = TopicMastery.objects.get_or_create(
        student=student, node=node, defaults={"branch_id": student.branch_id}
    )
    previous = TopicMastery.Level.NOT_STARTED if created else row.level
    with audit.track(row, "mastery"):
        row.level = level
        if notes is not None:
            row.notes = notes[:500]
        row.updated_by_user = user if getattr(user, "is_authenticated", False) else None
        row.save()
    if level != previous:
        publish(
            events.TopicMasteryChanged(
                subject_id=row.pk,
                student_id=str(student.pk),
                node_id=str(node.pk),
                level=level,
                previous=previous,
            ),
            branch_id=row.branch_id,
        )
    return row


def resolve_topics(values: Iterable[str], subject_id: Any = None) -> list[CurriculumNode]:
    """Match lesson report ``topics`` answers to curriculum topics: by id, code or name
    (the lesson's subject first). Free text that matches nothing is ignored."""
    import uuid

    topics = list(selectors.topic_nodes().filter(kind=CurriculumNode.Kind.TOPIC))
    topics.sort(key=lambda n: 0 if subject_id and n.curriculum.subject_id == subject_id else 1)
    by_id = {str(n.pk): n for n in topics}
    found: dict[str, CurriculumNode] = {}
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        try:
            node = by_id.get(str(uuid.UUID(value)))
        except ValueError:
            node = None
        if node is None:
            key = value.casefold()
            node = next((n for n in topics if n.code and n.code.casefold() == key), None)
            node = node or next((n for n in topics if n.name.casefold() == key), None)
        if node is not None:
            found[str(node.pk)] = node
    return list(found.values())


def topics_from_report(report_id: Any) -> list[LessonTopic]:
    """E09 → E21: a submitted report's ``topics`` answers tag its lesson."""
    from tutortrack.delivery.models import LessonReport

    report = (
        LessonReport.objects.select_related("lesson__service", "template_version")
        .filter(pk=report_id)
        .first()
    )
    if report is None:
        return []
    values: list[str] = []
    for f in report.template_version.fields:
        if f.get("type") == "topics":
            answer = report.answers.get(f["key"]) or []
            values += [str(v) for v in answer] if isinstance(answer, list) else []
    nodes = resolve_topics(values, report.lesson.service.subject_id)
    if not nodes:
        return []
    with transaction.atomic():
        return tag_lesson(report.lesson, nodes, report=report)


# --- goals (T04) --------------------------------------------------------------------------------


def _milestone_progress(goal: Goal) -> int | None:
    milestones = list(GoalMilestone.objects.filter(goal=goal))  # not a stale prefetch
    if not milestones:
        return None
    done = sum(1 for m in milestones if m.done_at)
    return int((Decimal(done) * 100 / len(milestones)).to_integral_value())


def _achieve(goal: Goal) -> None:
    goal.status = Goal.Status.ACHIEVED
    goal.achieved_at = now()
    goal.progress_percent = 100
    goal.save(update_fields=["status", "achieved_at", "progress_percent", "updated_at"])
    audit.record(goal, "achieve", {"status": ["active", "achieved"]})
    publish(
        events.GoalAchieved(subject_id=goal.pk, student_id=str(goal.student_id), title=goal.title),
        branch_id=goal.branch_id,
    )


@transaction.atomic
def save_goal(
    goal: Goal | None,
    *,
    user: Any = None,
    milestones: list[dict[str, Any]] | None = None,
    **data: Any,
) -> Goal:
    """Create or change a goal. With milestones, progress is the share done; without,
    the tutor sets ``progress_percent``."""
    created = goal is None
    goal = goal or Goal()
    student = data.get("student", goal.student if not created else None)
    if student is None:
        raise _invalid("student", _("Choose a student."))
    _check_students(user, "learning.goal.manage", [student])
    if not created and goal.status != Goal.Status.ACTIVE and "status" not in data:
        data.pop("progress_percent", None)
    pct = data.get("progress_percent")
    if pct is not None and not 0 <= int(pct) <= 100:
        raise _invalid("progress_percent", _("Progress is between 0 and 100%."))
    data["branch_id"] = student.branch_id
    _save(
        goal,
        created,
        data,
        (
            "student",
            "branch_id",
            "kind",
            "title",
            "description",
            "subject",
            "target_grade",
            "current_grade",
            "exam_date",
            "due_date",
            "progress_percent",
            "visible_to_family",
        ),
    )
    if milestones is not None:
        keep = {str(m["id"]) for m in milestones if m.get("id")}
        GoalMilestone.objects.filter(goal=goal).exclude(pk__in=keep).delete()
        existing = {str(m.pk): m for m in GoalMilestone.objects.filter(goal=goal)}
        for position, row in enumerate(milestones):
            ms = existing.get(str(row.get("id") or "")) or GoalMilestone(goal=goal)
            ms.title = str(row["title"])[:200]
            ms.due_date = row.get("due_date")
            if "done" in row:
                ms.done_at = (ms.done_at or now()) if row["done"] else None
            ms.position = position
            ms.save()
        audit.record(goal, "milestones", {"milestones": [None, len(milestones)]})
    auto = _milestone_progress(goal)
    if auto is not None and goal.progress_percent != auto:
        goal.progress_percent = auto
        goal.save(update_fields=["progress_percent", "updated_at"])
    if created:
        publish(
            events.GoalCreated(
                subject_id=goal.pk, student_id=str(student.pk), title=goal.title, kind=goal.kind
            ),
            branch_id=goal.branch_id,
        )
    if (
        auto == 100
        and goal.status == Goal.Status.ACTIVE
        and milestones
        and _setting("goals_auto_achieve")
    ):
        _achieve(goal)
    return goal


@transaction.atomic
def set_milestone_done(goal: Goal, milestone_id: Any, done: bool, *, user: Any = None) -> Goal:
    _check_students(user, "learning.goal.manage", [goal.student])
    milestone = GoalMilestone.objects.filter(goal=goal, pk=milestone_id).first()
    if milestone is None:
        raise _invalid("milestone", _("Unknown milestone."))
    with audit.track(milestone, "milestone"):
        milestone.done_at = (milestone.done_at or now()) if done else None
        milestone.save()
    goal.progress_percent = _milestone_progress(goal) or 0
    goal.save(update_fields=["progress_percent", "updated_at"])
    if (
        goal.progress_percent == 100
        and goal.status == Goal.Status.ACTIVE
        and _setting("goals_auto_achieve")
    ):
        _achieve(goal)
    return goal


@transaction.atomic
def set_goal_status(goal: Goal, status: str, *, user: Any = None) -> Goal:
    _check_students(user, "learning.goal.manage", [goal.student])
    if status == goal.status:
        return goal
    if status == Goal.Status.ACHIEVED:
        _achieve(goal)
        return goal
    with audit.track(goal, "status"):
        goal.status = status
        if status == Goal.Status.ACTIVE:
            goal.achieved_at = None
        goal.save(update_fields=["status", "achieved_at", "updated_at"])
    return goal


# --- assessments (T05) --------------------------------------------------------------------------


@transaction.atomic
def save_assessment(assessment: Assessment | None, **data: Any) -> Assessment:
    created = assessment is None
    assessment = assessment or Assessment()
    max_score = data.get("max_score", assessment.max_score)
    if max_score is not None and max_score <= 0:
        raise _invalid("max_score", _("The maximum score must be more than zero."))
    _save(
        assessment,
        created,
        data,
        ("name", "kind", "subject", "level", "held_on", "max_score", "grade_scale", "description"),
    )
    return assessment


@transaction.atomic
def record_result(
    *,
    assessment: Assessment,
    student: Student,
    user: Any = None,
    score: Decimal | None = None,
    max_score: Decimal | None = None,
    grade: str = "",
    **data: Any,
) -> AssessmentResult:
    """Record (or correct) a student's result; the percentage is worked out from the
    score (half-up, 2 places) when there is a maximum."""
    _check_students(user, "learning.assessment.manage", [student])
    max_score = max_score if max_score is not None else assessment.max_score
    if score is not None and score < 0:
        raise _invalid("score", _("The score can't be negative."))
    if max_score is not None and max_score <= 0:
        raise _invalid("max_score", _("The maximum score must be more than zero."))
    if score is not None and max_score is not None and score > max_score:
        raise _invalid("score", _("The score is more than the maximum."))
    if grade and assessment.grade_scale is not None:
        grade = marking.check_grade(
            assessment.grade_scale.kind, assessment.grade_scale.grades, grade
        )
    pct = marking.percent(score, max_score) if score is not None and max_score else None
    if pct is None and grade.endswith("%"):
        pct = Decimal(grade.rstrip("%"))
    existing = AssessmentResult.objects.filter(assessment=assessment, student=student).first()
    fields = {
        "assessment": assessment,
        "student": student,
        "branch_id": student.branch_id,
        "score": score,
        "max_score": max_score,
        "percent": pct,
        "grade": grade[:20],
        "taken_on": data.get("taken_on") or assessment.held_on,
        **{k: v for k, v in data.items() if k in {"notes", "attachment", "visible_to_family"}},
    }
    result = existing or AssessmentResult()
    _save(result, existing is None, fields, fields.keys())
    if existing is None:
        publish(
            events.AssessmentRecorded(
                subject_id=result.pk,
                assessment_id=str(assessment.pk),
                student_id=str(student.pk),
                kind=assessment.kind,
                percent=str(pct) if pct is not None else None,
                grade=result.grade,
            ),
            branch_id=result.branch_id,
        )
    return result


@transaction.atomic
def delete_result(result: AssessmentResult, *, user: Any = None) -> None:
    _check_students(user, "learning.assessment.manage", [result.student])
    audit.record(result, "delete", {"percent": [str(result.percent), None]})
    result.delete()


# --- quizzes (T08) ------------------------------------------------------------------------------


@transaction.atomic
def save_quiz(
    quiz: Quiz | None,
    *,
    user: Any = None,
    questions: list[dict[str, Any]] | None = None,
    **data: Any,
) -> Quiz:
    created = quiz is None
    quiz = quiz or Quiz()
    if created and _own_only(user, "learning.quiz.manage"):
        data["owner"] = tutor_of(user)
    elif (
        not created
        and _own_only(user, "learning.quiz.manage")
        and (quiz.owner is None or quiz.owner != tutor_of(user))
    ):
        raise PermissionDenied(_("You can only change your own quizzes."))
    _save(
        quiz,
        created,
        data,
        (
            "title",
            "description",
            "subject",
            "level",
            "purpose",
            "pass_percent",
            "time_limit_minutes",
            "owner",
        ),
    )
    if questions is not None:
        if not created and quiz.attempts.exists():
            raise Conflict(_("This quiz has been taken; copy it to change the questions."))
        if len(questions) > 100:
            raise _invalid("questions", _("A quiz can have at most 100 questions."))
        quiz.questions.all().delete()
        for position, row in enumerate(questions):
            kind = row.get("kind", QuizQuestion.Kind.SINGLE)
            if kind not in QuizQuestion.Kind.values:
                raise _invalid("questions", _("Unknown question type."))
            prompt = str(row.get("prompt", "")).strip()
            if not prompt:
                raise _invalid("questions", _("Every question needs a prompt."))
            choices, answer = marking.clean_question(kind, row.get("choices"), row.get("answer"))
            QuizQuestion.objects.create(
                quiz=quiz,
                position=position,
                kind=kind,
                prompt=prompt[:5000],
                choices=choices,
                answer=answer,
                points=max(1, min(int(row.get("points") or 1), 100)),
                explanation=str(row.get("explanation", ""))[:5000],
            )
        audit.record(quiz, "questions", {"questions": [None, len(questions)]})
    return quiz


@transaction.atomic
def set_quiz_archived(quiz: Quiz, archived: bool) -> Quiz:
    with audit.track(quiz, "archive" if archived else "unarchive"):
        quiz.archived_at = now() if archived else None
        quiz.save(update_fields=["archived_at", "updated_at"])
    return quiz


@transaction.atomic
def take_quiz(
    quiz: Quiz,
    *,
    answers: dict[str, Any],
    student: Student | None = None,
    user: Any = None,
    assignment: HomeworkAssignment | None = None,
) -> QuizAttempt:
    """Auto-mark an attempt. For homework, the result is also recorded as a *quiz*
    assessment so it shows in the score trend. ``student`` is empty for tutor subject
    tests (E18 seam: ``user`` is the applicant)."""
    if not isinstance(answers, dict):
        raise _invalid("quiz_answers", _("Answers must be an object."))
    questions = [
        {"id": str(q.pk), "kind": q.kind, "answer": q.answer, "points": q.points}
        for q in quiz.questions.all()
    ]
    if not questions:
        raise Conflict(_("The quiz has no questions."))
    marked = marking.mark_quiz(questions, {str(k): v for k, v in answers.items()})
    attempt = QuizAttempt.objects.create(
        quiz=quiz,
        student=student,
        user=user if getattr(user, "is_authenticated", False) else None,
        assignment=assignment,
        answers={str(k): v for k, v in answers.items() if str(k) in {q["id"] for q in questions}},
        marks=marked["marks"],
        score=marked["score"],
        max_score=marked["max_score"],
        percent=marked["percent"],
        passed=marked["percent"] >= quiz.pass_percent,
        submitted_at=now(),
    )
    publish(
        events.QuizSubmitted(
            subject_id=attempt.pk,
            quiz_id=str(quiz.pk),
            student_id=str(student.pk) if student else None,
            percent=str(attempt.percent),
            passed=attempt.passed,
        )
    )
    if student is not None and assignment is not None:
        homework = assignment.homework
        assessment = Assessment.objects.filter(source_key=f"homework:{homework.pk}").first()
        if assessment is None:
            assessment = Assessment.objects.create(
                name=homework.title,
                kind=Assessment.Kind.QUIZ,
                subject=quiz.subject,
                level=quiz.level,
                held_on=org_today(),
                max_score=attempt.max_score or None,
                source_key=f"homework:{homework.pk}",
            )
        record_result(
            assessment=assessment,
            student=student,
            score=attempt.score,
            max_score=attempt.max_score or None,
            taken_on=org_today(),
        )
    return attempt


# --- lending library (T07) ----------------------------------------------------------------------


@transaction.atomic
def save_item(item: LibraryItem | None, **data: Any) -> LibraryItem:
    created = item is None
    item = item or LibraryItem()
    cost: Money | None = data.pop(
        "replacement_cost", item.replacement_cost if not created else None
    )
    if cost is not None:
        if cost.is_negative():
            raise _invalid("replacement_cost", _("The cost can't be negative."))
        data["currency"] = cost.currency
        data["replacement_cost"] = cost
    elif created:
        from tutortrack.tenancy.models import Organisation

        data.setdefault("currency", Organisation.objects.get(pk=_org_id()).default_currency)
    if "quantity" in data and int(data["quantity"]) < 1:
        raise _invalid("quantity", _("Keep at least one."))
    _save(
        item,
        created,
        data,
        (
            "name",
            "kind",
            "description",
            "identifier",
            "quantity",
            "currency",
            "replacement_cost",
            "location",
            "branch",
        ),
    )
    return item


def _org_id() -> Any:
    from tutortrack.core.context import require_organisation_id

    return require_organisation_id()


@transaction.atomic
def set_item_archived(item: LibraryItem, archived: bool) -> LibraryItem:
    with audit.track(item, "archive" if archived else "unarchive"):
        item.archived_at = now() if archived else None
        item.save(update_fields=["archived_at", "updated_at"])
    return item


@transaction.atomic
def lend(
    item: LibraryItem,
    student: Student,
    *,
    due_date: date | None = None,
    notes: str = "",
    user: Any = None,
) -> Loan:
    item = LibraryItem.objects.select_for_update().get(pk=item.pk)
    if item.archived_at is not None:
        raise Conflict(_("This item is archived."))
    if selectors.available(item) < 1:
        raise Conflict(_("None left to lend."))
    today = org_today()
    due = due_date or today + timedelta(days=int(_setting("loan_days")))
    if due < today:
        raise _invalid("due_date", _("The due date is in the past."))
    loan = Loan.objects.create(
        item=item,
        student=student,
        branch_id=student.branch_id,
        lent_on=today,
        due_date=due,
        notes=notes[:500],
    )
    audit.record_create(loan)
    publish(
        events.LoanCreated(
            subject_id=loan.pk,
            item_id=str(item.pk),
            student_id=str(student.pk),
            due_date=due.isoformat(),
        ),
        branch_id=loan.branch_id,
    )
    return loan


@transaction.atomic
def return_loan(loan: Loan, *, returned_on: date | None = None, notes: str = "") -> Loan:
    if loan.status != Loan.Status.OUT:
        raise Conflict(_("This loan is already closed."))
    with audit.track(loan, "return"):
        loan.status = Loan.Status.RETURNED
        loan.returned_on = returned_on or org_today()
        loan.return_notes = notes[:500]
        loan.save()
    publish(
        events.LoanReturned(
            subject_id=loan.pk, item_id=str(loan.item_id), student_id=str(loan.student_id)
        ),
        branch_id=loan.branch_id,
    )
    return loan


@transaction.atomic
def extend_loan(loan: Loan, due_date: date) -> Loan:
    from tutortrack.core.workflows import signal

    from .processes import loan_workflow_id

    if loan.status != Loan.Status.OUT:
        raise Conflict(_("This loan is already closed."))
    if due_date <= loan.due_date:
        raise _invalid("due_date", _("Choose a later date."))
    with audit.track(loan, "extend"):
        loan.due_date = due_date
        if due_date >= org_today():
            loan.overdue_at = None
            loan.reminded_at = None
            loan.overdue_notices = 0
            loan.last_notice_at = None
        loan.save()
    signal(loan_workflow_id(loan.organisation_id, loan.pk), "changed")
    return loan


@transaction.atomic
def mark_lost(
    loan: Loan, *, charge: bool = False, amount: Money | None = None, user: Any = None
) -> Loan:
    """The item is lost: optionally bill the family the replacement cost as an E10 ad hoc
    charge (once per loan, so a retried request never bills twice)."""
    from tutortrack.billing import services as billing
    from tutortrack.billing.models import Charge

    loan = (
        Loan.objects.select_for_update().select_related("item", "student__client").get(pk=loan.pk)
    )
    if loan.status == Loan.Status.RETURNED:
        raise Conflict(_("This item was returned."))
    first_time = loan.status == Loan.Status.OUT
    charged: dict[str, str] | None = None
    if charge and not loan.replacement_charge_ids:
        price = amount or loan.item.replacement_cost
        if price is None or not price.is_positive():
            raise _invalid("amount", _("Enter the replacement cost."))
        charges = billing.charge_fee(
            client=loan.student.client,
            source_key=f"library-loan:{loan.pk}",
            description=_("Replacement: %(item)s") % {"item": loan.item.name},
            price=price,
            day=org_today(),
            student=loan.student,
            kind=Charge.Kind.AD_HOC,
            category="library",
            user=user,
        )
        loan.replacement_charge_ids = [str(c.pk) for c in charges]
        loan.replacement_charged_at = now()
        charged = price.to_dict()
    with audit.track(loan, "lost"):
        loan.status = Loan.Status.LOST
        loan.save()
    if first_time or charged:
        publish(
            events.LoanLost(
                subject_id=loan.pk,
                item_id=str(loan.item_id),
                student_id=str(loan.student_id),
                charged=charged,
            ),
            branch_id=loan.branch_id,
        )
    return loan


def _loan_due_at(loan: Loan) -> datetime:
    """A loan is overdue from the start of the day after its due date (org time)."""
    zone = org_zone()
    return datetime.combine(loan.due_date + timedelta(days=1), datetime.min.time(), tzinfo=zone)


def loan_state(loan_id: Any) -> dict[str, Any]:
    loan = Loan.objects.get(pk=loan_id)
    due_at = _loan_due_at(loan)
    days = int(_setting("loan_reminder_days"))
    remind_at = due_at - timedelta(days=days + 1) + timedelta(hours=9)
    every = timedelta(days=int(_setting("loan_overdue_notice_days")))
    last = loan.last_notice_at or loan.overdue_at
    return {
        "status": loan.status,
        "open": loan.status == Loan.Status.OUT,
        "due_at": due_at.isoformat(),
        "remind_at": remind_at.isoformat(),
        "remind": bool(days) and loan.reminded_at is None and remind_at > loan.created_at,
        "overdue": loan.overdue_at is not None,
        "notices": loan.overdue_notices,
        "max_notices": int(_setting("loan_overdue_notices")),
        "next_notice_at": (last + every).isoformat() if last else None,
    }


@transaction.atomic
def send_loan_reminder(loan_id: Any) -> bool:
    from tutortrack.comms import services as comms

    loan = Loan.objects.select_for_update().get(pk=loan_id)
    if loan.status != Loan.Status.OUT or loan.reminded_at is not None:
        return False
    loan.reminded_at = now()
    loan.save(update_fields=["reminded_at", "updated_at"])
    comms.notify("loan_due", loan, key=f"loan-due:{loan.pk}:{loan.due_date}")
    return True


@transaction.atomic
def mark_loan_overdue(loan_id: Any, *, dedupe_key: str | None = None) -> bool:
    from tutortrack.comms import services as comms

    loan = Loan.objects.select_for_update().get(pk=loan_id)
    if loan.status != Loan.Status.OUT or loan.overdue_at is not None:
        return False  # the workflow only calls this once its due timer fired
    loan.overdue_at = now()
    loan.save(update_fields=["overdue_at", "updated_at"])
    publish(
        events.LoanOverdue(
            subject_id=loan.pk,
            item_id=str(loan.item_id),
            student_id=str(loan.student_id),
            due_date=loan.due_date.isoformat(),
        ),
        branch_id=loan.branch_id,
        dedupe_key=dedupe_key,
    )
    comms.notify("loan_overdue", loan, key=f"loan-overdue:{loan.pk}:{loan.due_date}:0")
    return True


@transaction.atomic
def send_overdue_notice(loan_id: Any) -> bool:
    from tutortrack.comms import services as comms

    loan = Loan.objects.select_for_update().get(pk=loan_id)
    if loan.status != Loan.Status.OUT or loan.overdue_at is None:
        return False
    if loan.overdue_notices >= int(_setting("loan_overdue_notices")):
        return False
    loan.overdue_notices += 1
    loan.last_notice_at = now()
    loan.save(update_fields=["overdue_notices", "last_notice_at", "updated_at"])
    comms.notify(
        "loan_overdue", loan, key=f"loan-overdue:{loan.pk}:{loan.due_date}:{loan.overdue_notices}"
    )
    return True


# --- progress reports (T06) ---------------------------------------------------------------------


def _report_title(student: Student, period: str, first: date, last: date) -> str:
    if period == ProgressReport.Period.MONTHLY:
        label = first.strftime("%Y-%m")
    else:
        label = f"{first.isoformat()} \N{EN DASH} {last.isoformat()}"
    return _("Progress report: %(student)s, %(period)s") % {
        "student": student.full_name,
        "period": label,
    }


@transaction.atomic
def generate_progress_report(
    student: Student,
    *,
    period_start: date,
    period_end: date,
    period: str = ProgressReport.Period.TERMLY,
    title: str = "",
    author: TutorProfile | None = None,
    user: Any = None,
) -> ProgressReport:
    """Create the report (or refresh a draft's data) from attendance, lesson reports,
    topics, goals, assessments and homework in the period."""
    from .progress import build_snapshot

    if period_end < period_start:
        raise _invalid("period_end", _("The period ends before it starts."))
    _check_students(user, "learning.progress.write", [student])
    report = ProgressReport.objects.filter(
        student=student, period_start=period_start, period_end=period_end
    ).first()
    if report is not None and report.status != ProgressReport.Status.DRAFT:
        raise Conflict(_("A report for this period has already been submitted."))
    snapshot = build_snapshot(student, period_start, period_end)
    if report is None:
        report = ProgressReport.objects.create(
            student=student,
            branch_id=student.branch_id,
            period=period,
            period_start=period_start,
            period_end=period_end,
            title=title or _report_title(student, period, period_start, period_end),
            snapshot=snapshot,
            generated_at=now(),
            author=author or tutor_of(user),
        )
        audit.record_create(report)
        return report
    with audit.track(report, "regenerate"):
        report.snapshot = snapshot
        report.generated_at = now()
        if title:
            report.title = title
        report.save()
    return report


def students_with_lessons(first: date, last: date, user: Any = None) -> list[Student]:
    from tutortrack.scheduling.models import LessonAttendee

    start, end = selectors.period_bounds(first, last)
    ids = LessonAttendee.objects.filter(lesson__start__gte=start, lesson__start__lt=end).values(
        "student_id"
    )
    qs = Student.objects.filter(pk__in=ids, archived_at__isnull=True)
    if _own_only(user, "learning.progress.write"):
        qs = qs.filter(pk__in=tutor_students(user))
    return list(qs.order_by("last_name", "first_name"))


def generate_for_period(
    *,
    period_start: date,
    period_end: date,
    period: str,
    students: Iterable[Student] | None = None,
    user: Any = None,
) -> dict[str, int]:
    """Draft reports for many students (default: everyone with lessons in the period).
    Reports already submitted are left alone."""
    chosen = (
        list(students)
        if students is not None
        else students_with_lessons(period_start, period_end, user)
    )
    created = refreshed = skipped = 0
    for student in chosen:
        existed = ProgressReport.objects.filter(
            student=student, period_start=period_start, period_end=period_end
        ).first()
        if existed is not None and existed.status != ProgressReport.Status.DRAFT:
            skipped += 1
            continue
        generate_progress_report(
            student, period_start=period_start, period_end=period_end, period=period, user=user
        )
        if existed is None:
            created += 1
        else:
            refreshed += 1
    return {"created": created, "refreshed": refreshed, "skipped": skipped}


def _editable(report: ProgressReport, user: Any) -> None:
    _check_students(user, "learning.progress.write", [report.student])
    if report.status in {ProgressReport.Status.APPROVED, ProgressReport.Status.SHARED}:
        raise Conflict(_("Approved reports can't be changed; reopen it first."))


@transaction.atomic
def update_progress_report(
    report: ProgressReport, *, user: Any = None, **data: Any
) -> ProgressReport:
    _editable(report, user)
    with audit.track(report):
        if "title" in data:
            report.title = str(data["title"])[:200]
        if "summary" in data:
            report.summary = str(data["summary"])[:20000]
        report.save()
    return report


def _publish_progress(report: ProgressReport, event_cls: Any, **extra: Any) -> None:
    publish(
        event_cls(
            subject_id=report.pk,
            student_id=str(report.student_id),
            period_start=report.period_start.isoformat(),
            period_end=report.period_end.isoformat(),
            **extra,
        ),
        branch_id=report.branch_id,
    )


@transaction.atomic
def submit_progress_report(report: ProgressReport, *, user: Any = None) -> ProgressReport:
    """The tutor is done. With approval turned off the report is approved (and shared,
    by setting) straight away."""
    _editable(report, user)
    if report.status != ProgressReport.Status.DRAFT:
        raise Conflict(_("This report has already been submitted."))
    if not report.summary.strip():
        raise _invalid("summary", _("Add your summary comments first."))
    with audit.track(report, "submit"):
        report.status = ProgressReport.Status.SUBMITTED
        report.submitted_at = now()
        report.save()
    _publish_progress(report, events.ProgressReportSubmitted)
    if not _setting("progress_requires_approval"):
        return approve_progress_report(report, user=user, check=False)
    return report


@transaction.atomic
def approve_progress_report(
    report: ProgressReport, *, user: Any = None, check: bool = True
) -> ProgressReport:
    if check:
        _check_students(user, "learning.progress.approve", [report.student])
    if report.status not in {ProgressReport.Status.SUBMITTED, ProgressReport.Status.DRAFT}:
        raise Conflict(_("This report has already been approved."))
    if not report.summary.strip():
        raise _invalid("summary", _("Add summary comments before approving."))
    with audit.track(report, "approve"):
        report.status = ProgressReport.Status.APPROVED
        report.approved_at = now()
        report.approved_by = user if getattr(user, "is_authenticated", False) else None
        report.submitted_at = report.submitted_at or report.approved_at
        report.save()
    _publish_progress(report, events.ProgressReportApproved)
    if _setting("share_on_approval"):
        return share_progress_report(report, user=user)
    return report


@transaction.atomic
def share_progress_report(report: ProgressReport, *, user: Any = None) -> ProgressReport:
    """Families see it in the portal and get it by email with the PDF."""
    if report.status != ProgressReport.Status.APPROVED:
        raise Conflict(_("Approve the report before sharing it."))
    with audit.track(report, "share"):
        report.status = ProgressReport.Status.SHARED
        report.shared_at = now()
        report.save()
    _publish_progress(report, events.ProgressReportShared, client_id=str(report.student.client_id))
    return report


@transaction.atomic
def reopen_progress_report(report: ProgressReport, *, user: Any = None) -> ProgressReport:
    if report.status == ProgressReport.Status.SHARED:
        raise Conflict(_("Shared reports can't be reopened."))
    _check_students(user, "learning.progress.write", [report.student])
    with audit.track(report, "reopen"):
        report.status = ProgressReport.Status.DRAFT
        report.approved_at = None
        report.approved_by = None
        report.save()
    return report
