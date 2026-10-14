"""Learning tools (E21): resources, homework, curriculum and mastery, goals, assessments,
progress reports, the lending library and built-in quizzes.

Records about one learner (homework assignments, mastery, goals, results, progress
reports, loans) are branch-scoped through the student's branch. Tutors work with their
``own`` scope: students on their jobs, lessons and classes (``tutor_students``).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import F, Q, QuerySet
from django.utils.translation import gettext_lazy as _

from tutortrack.core.fields import CurrencyField, MoneyField
from tutortrack.core.models import BranchScopedModel, TenantModel


def tutor_students(user: Any) -> QuerySet[Any]:
    """Student ids a tutor works with: their jobs (E07), lessons they teach (E08) and the
    classes they teach (E20)."""
    from tutortrack.courses.models import Enrolment
    from tutortrack.people.models import Student
    from tutortrack.scheduling.models import LessonAttendee

    lessons = LessonAttendee.objects.filter(lesson__tutors__tutor__membership__user=user).values(
        "student_id"
    )
    classes = Enrolment.objects.filter(group_class__teachers__tutor__membership__user=user).values(
        "student_id"
    )
    return Student.objects.filter(
        Student.own_scope_q(user) | Q(pk__in=lessons) | Q(pk__in=classes)
    ).values("pk")


def _mine(user: Any, path: str = "student") -> Q:
    return Q(**{f"{path}__in": tutor_students(user)})


# --- resources (FR-21-1) ------------------------------------------------------------------------


class ResourceFolder(TenantModel):
    """A folder in the organisation library (``owner`` empty) or a tutor's own library."""

    name = models.CharField(max_length=120)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    owner = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(owner__membership__user=user) | Q(owner__isnull=True)


class Resource(TenantModel):
    class Kind(models.TextChoices):
        FILE = "file", _("File")
        LINK = "link", _("Link")

    class MediaType(models.TextChoices):
        PDF = "pdf", _("PDF")
        IMAGE = "image", _("Image")
        AUDIO = "audio", _("Audio")
        VIDEO = "video", _("Video")
        DOCUMENT = "document", _("Document")
        YOUTUBE = "youtube", _("YouTube")
        GOOGLE_DOCS = "google_docs", _("Google Docs")
        LINK = "link", _("Web link")

    class Visibility(models.TextChoices):
        STAFF = "staff", _("Staff only")
        TUTORS = "tutors", _("Staff and all tutors")
        PRIVATE = "private", _("Only the owner (and staff)")

    folder = models.ForeignKey(
        ResourceFolder, null=True, blank=True, on_delete=models.SET_NULL, related_name="resources"
    )
    owner = models.ForeignKey(  # a tutor's personal library; empty = organisation library
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=4, choices=Kind.choices)
    file = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    url = models.URLField(max_length=2000, blank=True, default="")
    media_type = models.CharField(max_length=12, choices=MediaType.choices, default="link")
    subject = models.ForeignKey(
        "catalogue.Subject", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    level = models.ForeignKey(
        "catalogue.Level", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    topics: models.ManyToManyField[Any, Any] = models.ManyToManyField(
        "CurriculumNode", blank=True, related_name="resources"
    )
    tags = models.JSONField(default=list, blank=True)
    visibility = models.CharField(
        max_length=8, choices=Visibility.choices, default=Visibility.TUTORS
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["title"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="file", file__isnull=False) | Q(kind="link") & ~Q(url=""),
                name="resource_has_content",
            )
        ]

    def __str__(self) -> str:
        return self.title

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        """A tutor's own resources, the organisation library open to tutors, and anything
        shared with their students."""
        shared = ResourceShare.objects.filter(
            Q(student__in=tutor_students(user)) | Q(lesson__tutors__tutor__membership__user=user)
        ).values("resource_id")
        return (
            Q(owner__membership__user=user)
            | Q(owner__isnull=True, visibility=cls.Visibility.TUTORS)
            | Q(pk__in=shared)
        )


class ResourceShare(TenantModel):
    """A resource shared with a student, a job's students, a lesson's attendees or a
    class (E20); they see it in the portal."""

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="shares")
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    lesson = models.ForeignKey(
        "scheduling.Lesson", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    group_class = models.ForeignKey(
        "courses.GroupClass", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    message = models.CharField(max_length=500, blank=True, default="")
    shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        student__isnull=False,
                        job__isnull=True,
                        lesson__isnull=True,
                        group_class__isnull=True,
                    )
                    | Q(
                        student__isnull=True,
                        job__isnull=False,
                        lesson__isnull=True,
                        group_class__isnull=True,
                    )
                    | Q(
                        student__isnull=True,
                        job__isnull=True,
                        lesson__isnull=False,
                        group_class__isnull=True,
                    )
                    | Q(
                        student__isnull=True,
                        job__isnull=True,
                        lesson__isnull=True,
                        group_class__isnull=False,
                    )
                ),
                name="resource_share_one_target",
            ),
        ]

    @property
    def target(self) -> tuple[str, Any]:
        for name in ("student", "job", "lesson", "group_class"):
            value = getattr(self, f"{name}_id")
            if value is not None:
                return name, value
        return "", None


class ResourceActivity(TenantModel):
    """Who opened a shared resource and how often (viewed / downloaded)."""

    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name="activity")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    views = models.PositiveIntegerField(default=0)
    downloads = models.PositiveIntegerField(default=0)
    first_opened_at = models.DateTimeField()
    last_opened_at = models.DateTimeField()

    class Meta(TenantModel.Meta):
        ordering = ["-last_opened_at"]
        constraints = [
            models.UniqueConstraint(fields=["resource", "user"], name="resource_activity_unique")
        ]


# --- homework (FR-21-2) -------------------------------------------------------------------------


class GradeScale(TenantModel):
    """How homework and assessments are graded: a percentage, letters, 9-1 or a custom
    list of grades (best first)."""

    class Kind(models.TextChoices):
        PERCENT = "percent", _("Percentage")
        LETTER = "letter", _("Letter grades")
        NUMERIC = "numeric", _("GCSE 9\N{EN DASH}1")
        CUSTOM = "custom", _("Custom")

    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    grades = models.JSONField(default=list, blank=True)
    is_default = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation"],
                condition=Q(is_default=True, archived_at__isnull=True),
                name="grade_scale_one_default",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Homework(TenantModel):
    class SubmissionType(models.TextChoices):
        FILE = "file", _("File upload")
        TEXT = "text", _("Written answer")
        LINK = "link", _("Link")
        NONE = "none", _("Mark as done")
        QUIZ = "quiz", _("Quiz")

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        CANCELLED = "cancelled", _("Cancelled")

    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True, default="")
    due_at = models.DateTimeField()
    expected_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    submission_type = models.CharField(
        max_length=4, choices=SubmissionType.choices, default=SubmissionType.TEXT
    )
    lesson = models.ForeignKey(
        "scheduling.Lesson", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    lesson_report = models.ForeignKey(
        "delivery.LessonReport",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    job = models.ForeignKey(
        "jobs.Job", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    group_class = models.ForeignKey(
        "courses.GroupClass", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    set_by = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    grade_scale = models.ForeignKey(
        GradeScale, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    quiz = models.ForeignKey(
        "Quiz", null=True, blank=True, on_delete=models.PROTECT, related_name="homework"
    )
    resources: models.ManyToManyField[Any, Any] = models.ManyToManyField(
        Resource, blank=True, related_name="homework"
    )
    attachments: models.ManyToManyField[Any, Any] = models.ManyToManyField(
        "core.StoredFile", blank=True, related_name="+"
    )
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.ACTIVE)

    class Meta(TenantModel.Meta):
        ordering = ["-due_at"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(submission_type="quiz") | Q(quiz__isnull=False),
                name="homework_quiz_needs_quiz",
            )
        ]

    def __str__(self) -> str:
        return self.title

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        mine = HomeworkAssignment.objects.filter(_mine(user)).values("homework_id")
        return Q(set_by__membership__user=user) | Q(pk__in=mine)


class HomeworkAssignment(BranchScopedModel):
    """Homework for one student: submission, review, grade and feedback."""

    class Status(models.TextChoices):
        ASSIGNED = "assigned", _("To do")
        SUBMITTED = "submitted", _("Submitted")
        RETURNED = "returned", _("Returned for resubmission")
        COMPLETED = "completed", _("Completed")
        EXCUSED = "excused", _("Excused")
        CANCELLED = "cancelled", _("Cancelled")

    OPEN = (Status.ASSIGNED, Status.RETURNED)

    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="assignments")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.ASSIGNED)
    round = models.PositiveSmallIntegerField(default=1)  # +1 each resubmission request
    round_started_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField()  # the homework's, or a later one on resubmission
    submitted_at = models.DateTimeField(null=True, blank=True)
    is_late = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    grade = models.CharField(max_length=20, blank=True, default="")
    score_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True, default="")
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    overdue_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["due_at"]
        constraints = [
            models.UniqueConstraint(fields=["homework", "student"], name="homework_student_unique")
        ]
        indexes = [models.Index(fields=["organisation", "status", "due_at"], name="hw_due_idx")]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _mine(user) | Q(homework__set_by__membership__user=user)

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN


class HomeworkSubmission(TenantModel):
    assignment = models.ForeignKey(
        HomeworkAssignment, on_delete=models.CASCADE, related_name="submissions"
    )
    attempt = models.PositiveSmallIntegerField()
    body = models.TextField(blank=True, default="")
    link = models.URLField(max_length=2000, blank=True, default="")
    files: models.ManyToManyField[Any, Any] = models.ManyToManyField(
        "core.StoredFile", blank=True, related_name="+"
    )
    quiz_attempt = models.ForeignKey(
        "QuizAttempt", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_late = models.BooleanField(default=False)

    class Meta(TenantModel.Meta):
        ordering = ["attempt"]
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "attempt"], name="homework_submission_attempt_unique"
            )
        ]


# --- curriculum and topics (FR-21-3) ------------------------------------------------------------


class Curriculum(TenantModel):
    """A specification tree: Subject/Level → units → topics."""

    name = models.CharField(max_length=150)
    subject = models.ForeignKey(
        "catalogue.Subject", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    level = models.ForeignKey(
        "catalogue.Level", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    exam_board = models.CharField(max_length=60, blank=True, default="")
    description = models.TextField(blank=True, default="")
    source_key = models.CharField(max_length=60, blank=True, default="")  # built-in spec
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class CurriculumNode(TenantModel):
    class Kind(models.TextChoices):
        UNIT = "unit", _("Unit")
        TOPIC = "topic", _("Topic")

    curriculum = models.ForeignKey(Curriculum, on_delete=models.CASCADE, related_name="nodes")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    kind = models.CharField(max_length=5, choices=Kind.choices, default=Kind.TOPIC)
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=40, blank=True, default="")
    position = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["curriculum", "position", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["curriculum", "code"],
                condition=~Q(code=""),
                name="curriculum_node_code_unique",
            )
        ]

    def __str__(self) -> str:
        return self.name


class LessonTopic(TenantModel):
    """A topic covered in a lesson (from the lesson report's topics field, E09)."""

    lesson = models.ForeignKey("scheduling.Lesson", on_delete=models.CASCADE, related_name="+")
    node = models.ForeignKey(CurriculumNode, on_delete=models.CASCADE, related_name="lessons")
    report = models.ForeignKey(
        "delivery.LessonReport", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tagged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(TenantModel.Meta):
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["lesson", "node"], name="lesson_topic_unique")
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(lesson__tutors__tutor__membership__user=user)


class TopicMastery(BranchScopedModel):
    class Level(models.TextChoices):
        NOT_STARTED = "not_started", _("Not started")
        LEARNING = "learning", _("Learning")
        SECURE = "secure", _("Secure")
        MASTERED = "mastered", _("Mastered")

    RANK = {"not_started": 0, "learning": 1, "secure": 2, "mastered": 3}

    student = models.ForeignKey("people.Student", on_delete=models.CASCADE, related_name="+")
    node = models.ForeignKey(CurriculumNode, on_delete=models.CASCADE, related_name="mastery")
    level = models.CharField(max_length=11, choices=Level.choices, default=Level.NOT_STARTED)
    covered_count = models.PositiveIntegerField(default=0)
    last_covered_at = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True, default="")
    updated_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta(BranchScopedModel.Meta):
        ordering = ["node__position"]
        constraints = [
            models.UniqueConstraint(fields=["student", "node"], name="topic_mastery_unique")
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _mine(user)


# --- goals (FR-21-4) ----------------------------------------------------------------------------


class Goal(BranchScopedModel):
    class Kind(models.TextChoices):
        TARGET_GRADE = "target_grade", _("Target grade")
        EXAM = "exam", _("Exam")
        CUSTOM = "custom", _("SMART goal")

    class Status(models.TextChoices):
        ACTIVE = "active", _("In progress")
        ACHIEVED = "achieved", _("Achieved")
        ABANDONED = "abandoned", _("Stopped")

    student = models.ForeignKey("people.Student", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.CUSTOM)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    subject = models.ForeignKey(
        "catalogue.Subject", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    target_grade = models.CharField(max_length=20, blank=True, default="")
    current_grade = models.CharField(max_length=20, blank=True, default="")
    exam_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.ACTIVE)
    progress_percent = models.PositiveSmallIntegerField(default=0)
    achieved_at = models.DateTimeField(null=True, blank=True)
    visible_to_family = models.BooleanField(default=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["status", "due_date", "title"]
        constraints = [
            models.CheckConstraint(
                condition=Q(progress_percent__lte=100), name="goal_progress_percent"
            )
        ]

    def __str__(self) -> str:
        return self.title

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _mine(user)


class GoalMilestone(TenantModel):
    goal = models.ForeignKey(Goal, on_delete=models.CASCADE, related_name="milestones")
    title = models.CharField(max_length=200)
    due_date = models.DateField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["position", "created_at"]


# --- assessments (FR-21-5) ----------------------------------------------------------------------


class Assessment(TenantModel):
    class Kind(models.TextChoices):
        DIAGNOSTIC = "diagnostic", _("Diagnostic")
        MOCK_EXAM = "mock_exam", _("Mock exam")
        QUIZ = "quiz", _("Quiz")
        SCHOOL_REPORT = "school_report", _("School report")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=13, choices=Kind.choices, default=Kind.OTHER)
    subject = models.ForeignKey(
        "catalogue.Subject", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    level = models.ForeignKey(
        "catalogue.Level", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    held_on = models.DateField()
    max_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    grade_scale = models.ForeignKey(
        GradeScale, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    description = models.TextField(blank=True, default="")
    source_key = models.CharField(max_length=80, blank=True, default="")  # e.g. a quiz homework

    class Meta(TenantModel.Meta):
        ordering = ["-held_on", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organisation", "source_key"],
                condition=~Q(source_key=""),
                name="assessment_source_unique",
            )
        ]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        mine = AssessmentResult.objects.filter(_mine(user)).values("assessment_id")
        return Q(pk__in=mine) | Q(created_by=user)


class AssessmentResult(BranchScopedModel):
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="results")
    student = models.ForeignKey("people.Student", on_delete=models.CASCADE, related_name="+")
    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    max_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=20, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    attachment = models.ForeignKey(
        "core.StoredFile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    taken_on = models.DateField()
    visible_to_family = models.BooleanField(default=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["taken_on"]
        constraints = [
            models.UniqueConstraint(
                fields=["assessment", "student"], name="assessment_result_unique"
            ),
            models.CheckConstraint(
                condition=Q(score__isnull=True)
                | Q(max_score__isnull=True)
                | Q(score__lte=F("max_score")),
                name="assessment_score_within_max",
            ),
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _mine(user)


# --- progress reports (FR-21-6) -----------------------------------------------------------------


class ProgressReport(BranchScopedModel):
    class Period(models.TextChoices):
        MONTHLY = "monthly", _("Monthly")
        TERMLY = "termly", _("Termly")
        CUSTOM = "custom", _("Custom period")

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        SUBMITTED = "submitted", _("Waiting for approval")
        APPROVED = "approved", _("Approved")
        SHARED = "shared", _("Shared with the family")

    student = models.ForeignKey("people.Student", on_delete=models.CASCADE, related_name="+")
    period = models.CharField(max_length=7, choices=Period.choices, default=Period.TERMLY)
    period_start = models.DateField()
    period_end = models.DateField()
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.DRAFT)
    summary = models.TextField(blank=True, default="")
    snapshot = models.JSONField(default=dict, blank=True)  # attendance, topics, goals...
    generated_at = models.DateTimeField(null=True, blank=True)
    author = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    shared_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["-period_end", "student"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "period_start", "period_end"], name="progress_report_period"
            ),
            models.CheckConstraint(
                condition=Q(period_end__gte=F("period_start")), name="progress_report_dates"
            ),
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _mine(user) | Q(author__membership__user=user)


# --- lending library (FR-21-7) ------------------------------------------------------------------


class LibraryItem(BranchScopedModel):
    class Kind(models.TextChoices):
        BOOK = "book", _("Book")
        INSTRUMENT = "instrument", _("Instrument")
        DEVICE = "device", _("Device")
        OTHER = "other", _("Other")

    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.BOOK)
    description = models.TextField(blank=True, default="")
    identifier = models.CharField(max_length=100, blank=True, default="")  # ISBN, serial
    quantity = models.PositiveIntegerField(default=1)
    currency = CurrencyField()
    replacement_cost = MoneyField(null=True, blank=True)
    location = models.CharField(max_length=200, blank=True, default="")
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(pk__in=Loan.objects.filter(_mine(user)).values("item_id"))


class Loan(BranchScopedModel):
    class Status(models.TextChoices):
        OUT = "out", _("On loan")
        RETURNED = "returned", _("Returned")
        LOST = "lost", _("Lost")

    item = models.ForeignKey(LibraryItem, on_delete=models.PROTECT, related_name="loans")
    student = models.ForeignKey("people.Student", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OUT)
    lent_on = models.DateField()
    due_date = models.DateField()
    returned_on = models.DateField(null=True, blank=True)
    notes = models.CharField(max_length=500, blank=True, default="")
    return_notes = models.CharField(max_length=500, blank=True, default="")
    reminded_at = models.DateTimeField(null=True, blank=True)
    overdue_at = models.DateTimeField(null=True, blank=True)
    overdue_notices = models.PositiveSmallIntegerField(default=0)
    last_notice_at = models.DateTimeField(null=True, blank=True)
    replacement_charge_ids = models.JSONField(default=list, blank=True)
    replacement_charged_at = models.DateTimeField(null=True, blank=True)

    class Meta(BranchScopedModel.Meta):
        ordering = ["due_date"]
        constraints = [
            models.CheckConstraint(condition=Q(due_date__gte=F("lent_on")), name="loan_dates")
        ]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _mine(user)


# --- built-in quizzes (FR-21-5, Phase 3b) -------------------------------------------------------


class Quiz(TenantModel):
    class Purpose(models.TextChoices):
        LEARNING = "learning", _("Homework and practice")
        TUTOR_TEST = "tutor_test", _("Tutor subject test (E18)")

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    subject = models.ForeignKey(
        "catalogue.Subject", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    level = models.ForeignKey(
        "catalogue.Level", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    purpose = models.CharField(max_length=10, choices=Purpose.choices, default=Purpose.LEARNING)
    pass_percent = models.PositiveSmallIntegerField(default=50)
    time_limit_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    owner = models.ForeignKey(
        "people.TutorProfile", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ["title"]
        constraints = [
            models.CheckConstraint(condition=Q(pass_percent__lte=100), name="quiz_pass_percent")
        ]

    def __str__(self) -> str:
        return self.title

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return Q(owner__membership__user=user) | Q(owner__isnull=True)


class QuizQuestion(TenantModel):
    class Kind(models.TextChoices):
        SINGLE = "single", _("Multiple choice (one answer)")
        MULTIPLE = "multiple", _("Multiple choice (several answers)")
        SHORT = "short", _("Short answer")

    quiz = models.ForeignKey(Quiz, on_delete=models.CASCADE, related_name="questions")
    position = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=8, choices=Kind.choices, default=Kind.SINGLE)
    prompt = models.TextField()
    choices = models.JSONField(default=list, blank=True)  # [{"id": "a", "text": "..."}]
    answer = models.JSONField(default=list)  # correct choice ids, or accepted short answers
    points = models.PositiveSmallIntegerField(default=1)
    explanation = models.TextField(blank=True, default="")

    class Meta(TenantModel.Meta):
        ordering = ["position", "created_at"]


class QuizAttempt(TenantModel):
    quiz = models.ForeignKey(Quiz, on_delete=models.PROTECT, related_name="attempts")
    student = models.ForeignKey(
        "people.Student", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    assignment = models.ForeignKey(
        HomeworkAssignment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quiz_attempts",
    )
    answers = models.JSONField(default=dict)
    marks = models.JSONField(default=dict)  # {question_id: {"correct": bool, "points": n}}
    score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    max_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    passed = models.BooleanField(default=False)
    submitted_at = models.DateTimeField()

    class Meta(TenantModel.Meta):
        ordering = ["-submitted_at"]

    @classmethod
    def own_scope_q(cls, user: Any) -> Q:
        return _mine(user) | Q(quiz__owner__membership__user=user)
