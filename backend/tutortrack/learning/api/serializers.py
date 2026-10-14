"""Serializers for learning tools (E21)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from tutortrack.catalogue.models import Level, Subject
from tutortrack.core.api.serializers import (
    BaseModelSerializer,
    MoneySerializerField,
    TenantRelatedField,
)
from tutortrack.core.models import StoredFile
from tutortrack.courses.models import GroupClass
from tutortrack.delivery.models import LessonReport
from tutortrack.jobs.models import Job
from tutortrack.people.models import Student, TutorProfile
from tutortrack.scheduling.models import Lesson

from .. import progress, selectors
from ..models import (
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
)


class FileRef(serializers.Serializer):
    id = serializers.UUIDField()
    filename = serializers.CharField()
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField()


def file_refs(files: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": f.pk,
            "filename": f.filename,
            "content_type": f.content_type,
            "size_bytes": f.size_bytes,
        }
        for f in files
    ]


class LearningArchiveSerializer(serializers.Serializer):
    archived = serializers.BooleanField()


# --- resources ----------------------------------------------------------------------------------


class ResourceFolderSerializer(BaseModelSerializer):
    parent = TenantRelatedField(ResourceFolder, required=False, allow_null=True)  # type: ignore[assignment]
    owner = TenantRelatedField(TutorProfile, required=False, allow_null=True)

    class Meta:
        model = ResourceFolder
        fields = ["id", "name", "parent", "owner", "created_at"]
        read_only_fields = ["id", "created_at"]


class ResourceSerializer(BaseModelSerializer):
    file = TenantRelatedField(StoredFile, required=False, allow_null=True)
    folder = TenantRelatedField(ResourceFolder, required=False, allow_null=True)
    owner = TenantRelatedField(TutorProfile, required=False, allow_null=True)
    subject = TenantRelatedField(Subject, required=False, allow_null=True)
    level = TenantRelatedField(Level, required=False, allow_null=True)
    topics = TenantRelatedField(CurriculumNode, many=True, required=False)
    tags = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, max_length=20
    )
    url = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    file_name = serializers.CharField(source="file.filename", read_only=True, default="")
    file_size = serializers.IntegerField(source="file.size_bytes", read_only=True, default=None)
    owner_name = serializers.SerializerMethodField()
    share_count = serializers.SerializerMethodField()

    class Meta:
        model = Resource
        fields = [
            "id",
            "title",
            "description",
            "kind",
            "file",
            "file_name",
            "file_size",
            "url",
            "media_type",
            "folder",
            "owner",
            "owner_name",
            "subject",
            "level",
            "topics",
            "tags",
            "visibility",
            "share_count",
            "archived_at",
            "created_at",
        ]
        read_only_fields = ["id", "media_type", "archived_at", "created_at"]

    @extend_schema_field(serializers.CharField())
    def get_owner_name(self, obj: Resource) -> str:
        return obj.owner.full_name if obj.owner else ""

    @extend_schema_field(serializers.IntegerField())
    def get_share_count(self, obj: Resource) -> int:
        return obj.shares.count()


class ShareRequestSerializer(serializers.Serializer):
    students = TenantRelatedField(Student, many=True, required=False)
    jobs = TenantRelatedField(Job, many=True, required=False)
    lessons = TenantRelatedField(Lesson, many=True, required=False)
    classes = TenantRelatedField(GroupClass, many=True, required=False)
    message = serializers.CharField(max_length=500, required=False, allow_blank=True)


class ResourceShareSerializer(BaseModelSerializer):
    resource_title = serializers.CharField(source="resource.title", read_only=True)
    target = serializers.SerializerMethodField()
    target_id = serializers.SerializerMethodField()
    target_name = serializers.SerializerMethodField()

    class Meta:
        model = ResourceShare
        fields = [
            "id",
            "resource",
            "resource_title",
            "target",
            "target_id",
            "target_name",
            "message",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(
        serializers.ChoiceField(choices=["student", "job", "lesson", "group_class"])
    )
    def get_target(self, obj: ResourceShare) -> str:
        return obj.target[0]

    @extend_schema_field(serializers.UUIDField())
    def get_target_id(self, obj: ResourceShare) -> str:
        return str(obj.target[1])

    @extend_schema_field(serializers.CharField())
    def get_target_name(self, obj: ResourceShare) -> str:
        kind = obj.target[0]
        if kind == "student" and obj.student:
            return obj.student.full_name
        if kind == "job" and obj.job:
            return str(obj.job)
        if kind == "lesson" and obj.lesson:
            return obj.lesson.title
        if kind == "group_class" and obj.group_class:
            return obj.group_class.name
        return ""


class ResourceActivitySerializer(BaseModelSerializer):
    user_name = serializers.SerializerMethodField()
    student_name = serializers.CharField(source="student.full_name", read_only=True, default="")

    class Meta:
        model = ResourceActivity
        fields = [
            "id",
            "user_name",
            "student",
            "student_name",
            "views",
            "downloads",
            "first_opened_at",
            "last_opened_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_user_name(self, obj: ResourceActivity) -> str:
        return obj.user.get_full_name() or obj.user.email


class OpenResourceSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_in = serializers.IntegerField(allow_null=True)
    kind = serializers.ChoiceField(choices=Resource.Kind.choices)


class StorageUsageSerializer(serializers.Serializer):
    used_bytes = serializers.IntegerField()
    library_bytes = serializers.IntegerField()
    limit_gb = serializers.IntegerField(allow_null=True)


# --- grade scales and homework ------------------------------------------------------------------


class GradeScaleSerializer(BaseModelSerializer):
    grades = serializers.ListField(
        child=serializers.CharField(max_length=20), required=False, max_length=30
    )

    class Meta:
        model = GradeScale
        fields = ["id", "name", "kind", "grades", "is_default", "created_at"]
        read_only_fields = ["id", "created_at"]


class SubmissionSerializer(BaseModelSerializer):
    files = serializers.SerializerMethodField()
    submitted_by_name = serializers.SerializerMethodField()

    class Meta:
        model = HomeworkSubmission
        fields = [
            "id",
            "attempt",
            "body",
            "link",
            "files",
            "quiz_attempt",
            "submitted_by_name",
            "is_late",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(FileRef(many=True))
    def get_files(self, obj: HomeworkSubmission) -> list[dict[str, Any]]:
        return file_refs(obj.files.all())

    @extend_schema_field(serializers.CharField())
    def get_submitted_by_name(self, obj: HomeworkSubmission) -> str:
        user = obj.submitted_by
        return (user.get_full_name() or user.email) if user else ""


class AssignmentCounts(serializers.Serializer):
    total = serializers.IntegerField()
    submitted = serializers.IntegerField()
    completed = serializers.IntegerField()
    overdue = serializers.IntegerField()


class HomeworkSerializer(BaseModelSerializer):
    set_by_name = serializers.SerializerMethodField()
    quiz_title = serializers.CharField(source="quiz.title", read_only=True, default="")
    attachment_files = serializers.SerializerMethodField()
    counts = serializers.SerializerMethodField()

    class Meta:
        model = Homework
        fields = [
            "id",
            "title",
            "instructions",
            "due_at",
            "expected_minutes",
            "submission_type",
            "lesson",
            "lesson_report",
            "job",
            "group_class",
            "set_by",
            "set_by_name",
            "grade_scale",
            "quiz",
            "quiz_title",
            "resources",
            "attachment_files",
            "status",
            "counts",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_set_by_name(self, obj: Homework) -> str:
        return obj.set_by.full_name if obj.set_by else ""

    @extend_schema_field(FileRef(many=True))
    def get_attachment_files(self, obj: Homework) -> list[dict[str, Any]]:
        return file_refs(obj.attachments.all())

    @extend_schema_field(AssignmentCounts)
    def get_counts(self, obj: Homework) -> dict[str, int]:
        from django.db.models import Count, Q

        from tutortrack.core.time import now

        return obj.assignments.exclude(status="cancelled").aggregate(
            total=Count("pk"),
            submitted=Count("pk", filter=Q(status="submitted")),
            completed=Count("pk", filter=Q(status="completed")),
            overdue=Count("pk", filter=Q(status__in=HomeworkAssignment.OPEN, due_at__lt=now())),
        )


class HomeworkCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    instructions = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    due_at = serializers.DateTimeField()
    expected_minutes = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=600
    )
    submission_type = serializers.ChoiceField(
        choices=Homework.SubmissionType.choices, required=False
    )
    students = TenantRelatedField(Student, many=True, required=False)
    group_class = TenantRelatedField(GroupClass, required=False, allow_null=True)
    job = TenantRelatedField(Job, required=False, allow_null=True)
    lesson = TenantRelatedField(Lesson, required=False, allow_null=True)
    lesson_report = TenantRelatedField(LessonReport, required=False, allow_null=True)
    set_by = TenantRelatedField(TutorProfile, required=False, allow_null=True)
    grade_scale = TenantRelatedField(GradeScale, required=False, allow_null=True)
    quiz = TenantRelatedField(Quiz, required=False, allow_null=True)
    resources = TenantRelatedField(Resource, many=True, required=False)
    attachments = TenantRelatedField(StoredFile, many=True, required=False)


class HomeworkUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    instructions = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    due_at = serializers.DateTimeField(required=False)
    expected_minutes = serializers.IntegerField(
        required=False, allow_null=True, min_value=1, max_value=600
    )
    grade_scale = TenantRelatedField(GradeScale, required=False, allow_null=True)
    resources = TenantRelatedField(Resource, many=True, required=False)


class AssignmentSerializer(BaseModelSerializer):
    homework_title = serializers.CharField(source="homework.title", read_only=True)
    submission_type = serializers.CharField(source="homework.submission_type", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    submissions = SubmissionSerializer(many=True, read_only=True)

    class Meta:
        model = HomeworkAssignment
        fields = [
            "id",
            "homework",
            "homework_title",
            "submission_type",
            "student",
            "student_name",
            "status",
            "round",
            "due_at",
            "submitted_at",
            "is_late",
            "completed_at",
            "grade",
            "score_percent",
            "feedback",
            "reviewed_at",
            "reminded_at",
            "overdue_at",
            "submissions",
        ]
        read_only_fields = fields


class ReviewSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["complete", "resubmit"])
    grade = serializers.CharField(max_length=20, required=False, allow_blank=True)
    feedback = serializers.CharField(max_length=10000, required=False, allow_blank=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)


class HomeworkStatsSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    submitted = serializers.IntegerField()
    completed = serializers.IntegerField()
    late = serializers.IntegerField()
    due = serializers.IntegerField()
    overdue = serializers.IntegerField()
    on_time = serializers.IntegerField()
    completion_rate = serializers.CharField(allow_null=True)


# --- curriculum ---------------------------------------------------------------------------------


class CurriculumSerializer(BaseModelSerializer):
    subject = TenantRelatedField(Subject, required=False, allow_null=True)
    level = TenantRelatedField(Level, required=False, allow_null=True)
    topic_count = serializers.SerializerMethodField()

    class Meta:
        model = Curriculum
        fields = [
            "id",
            "name",
            "subject",
            "level",
            "exam_board",
            "description",
            "source_key",
            "topic_count",
            "archived_at",
            "created_at",
        ]
        read_only_fields = ["id", "source_key", "archived_at", "created_at"]

    @extend_schema_field(serializers.IntegerField())
    def get_topic_count(self, obj: Curriculum) -> int:
        return obj.nodes.filter(kind=CurriculumNode.Kind.TOPIC).count()


class CurriculumNodeSerializer(BaseModelSerializer):
    curriculum = TenantRelatedField(Curriculum)
    parent = TenantRelatedField(CurriculumNode, required=False, allow_null=True)  # type: ignore[assignment]

    class Meta:
        model = CurriculumNode
        fields = ["id", "curriculum", "parent", "kind", "name", "code", "position"]
        read_only_fields = ["id"]
        extra_kwargs = {"position": {"required": False}}


class TreeTopicSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField(allow_blank=True)
    position = serializers.IntegerField()


class TreeUnitSerializer(TreeTopicSerializer):
    topics = TreeTopicSerializer(many=True)


class BuiltinCurriculumSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    subject = serializers.CharField()
    level = serializers.CharField()
    exam_board = serializers.CharField(allow_blank=True)
    units = serializers.IntegerField()
    topics = serializers.IntegerField()
    installed = serializers.BooleanField()


class InstallBuiltinSerializer(serializers.Serializer):
    key = serializers.CharField(max_length=60, help_text="A key from /learning/curricula/builtins")
    subject = TenantRelatedField(Subject, required=False, allow_null=True)
    level = TenantRelatedField(Level, required=False, allow_null=True)


class CsvImportSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=500_000)


class CsvImportResultSerializer(serializers.Serializer):
    units = serializers.IntegerField()
    topics = serializers.IntegerField()
    skipped = serializers.IntegerField()


class TopicSuggestionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField(allow_blank=True)
    unit = serializers.CharField(allow_blank=True)
    curriculum = serializers.CharField()
    curriculum_id = serializers.UUIDField()


class LessonTopicSerializer(BaseModelSerializer):
    node_name = serializers.CharField(source="node.name", read_only=True)
    curriculum_name = serializers.CharField(source="node.curriculum.name", read_only=True)

    class Meta:
        model = LessonTopic
        fields = ["id", "lesson", "node", "node_name", "curriculum_name", "report", "created_at"]
        read_only_fields = fields


class TagLessonSerializer(serializers.Serializer):
    lesson = TenantRelatedField(Lesson)
    nodes = TenantRelatedField(CurriculumNode, many=True)


class MasterySerializer(BaseModelSerializer):
    node_name = serializers.CharField(source="node.name", read_only=True)
    curriculum_name = serializers.CharField(source="node.curriculum.name", read_only=True)

    class Meta:
        model = TopicMastery
        fields = [
            "id",
            "student",
            "node",
            "node_name",
            "curriculum_name",
            "level",
            "covered_count",
            "last_covered_at",
            "notes",
            "updated_at",
        ]
        read_only_fields = fields


class SetMasterySerializer(serializers.Serializer):
    student = TenantRelatedField(Student)
    node = TenantRelatedField(CurriculumNode)
    level = serializers.ChoiceField(choices=TopicMastery.Level.choices)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class CoverageTopicSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField(allow_blank=True)
    level = serializers.ChoiceField(choices=TopicMastery.Level.choices)
    lessons = serializers.IntegerField()
    last_covered = serializers.DateTimeField(allow_null=True)


class CoverageUnitSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    topics = CoverageTopicSerializer(many=True)


class LearningRef(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class MasterySummarySerializer(serializers.Serializer):
    not_started = serializers.IntegerField()
    learning = serializers.IntegerField()
    secure = serializers.IntegerField()
    mastered = serializers.IntegerField()


class CoverageSerializer(serializers.Serializer):
    curriculum = LearningRef()
    units = CoverageUnitSerializer(many=True)
    summary = MasterySummarySerializer()
    covered = serializers.IntegerField()
    topics = serializers.IntegerField()


# --- goals and assessments ----------------------------------------------------------------------


class MilestoneSerializer(BaseModelSerializer):
    id = serializers.UUIDField(required=False)
    done = serializers.BooleanField(required=False)

    class Meta:
        model = GoalMilestone
        fields = ["id", "title", "due_date", "done", "done_at"]
        read_only_fields = ["done_at"]

    def to_representation(self, instance: Any) -> dict[str, Any]:
        out: dict[str, Any] = super().to_representation(instance)
        out["done"] = instance.done_at is not None
        return out


class GoalSerializer(BaseModelSerializer):
    student = TenantRelatedField(Student)
    subject = TenantRelatedField(Subject, required=False, allow_null=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    milestones = MilestoneSerializer(many=True, required=False)

    class Meta:
        model = Goal
        fields = [
            "id",
            "student",
            "student_name",
            "kind",
            "title",
            "description",
            "subject",
            "target_grade",
            "current_grade",
            "exam_date",
            "due_date",
            "status",
            "progress_percent",
            "achieved_at",
            "visible_to_family",
            "milestones",
            "created_at",
        ]
        read_only_fields = ["id", "status", "achieved_at", "created_at"]
        extra_kwargs = {"progress_percent": {"min_value": 0, "max_value": 100}}


class GoalStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Goal.Status.choices)


class MilestoneDoneSerializer(serializers.Serializer):
    milestone = serializers.UUIDField()
    done = serializers.BooleanField()


class AssessmentSerializer(BaseModelSerializer):
    subject = TenantRelatedField(Subject, required=False, allow_null=True)
    level = TenantRelatedField(Level, required=False, allow_null=True)
    grade_scale = TenantRelatedField(GradeScale, required=False, allow_null=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True, default="")
    results_count = serializers.SerializerMethodField()

    class Meta:
        model = Assessment
        fields = [
            "id",
            "name",
            "kind",
            "subject",
            "subject_name",
            "level",
            "held_on",
            "max_score",
            "grade_scale",
            "description",
            "results_count",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    @extend_schema_field(serializers.IntegerField())
    def get_results_count(self, obj: Assessment) -> int:
        return obj.results.count()


class ResultSerializer(BaseModelSerializer):
    assessment = TenantRelatedField(Assessment)
    student = TenantRelatedField(Student)
    attachment = TenantRelatedField(StoredFile, required=False, allow_null=True)
    assessment_name = serializers.CharField(source="assessment.name", read_only=True)
    assessment_kind = serializers.CharField(source="assessment.kind", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)

    class Meta:
        model = AssessmentResult
        fields = [
            "id",
            "assessment",
            "assessment_name",
            "assessment_kind",
            "student",
            "student_name",
            "score",
            "max_score",
            "percent",
            "grade",
            "notes",
            "attachment",
            "taken_on",
            "visible_to_family",
            "created_at",
        ]
        read_only_fields = ["id", "percent", "created_at"]
        extra_kwargs = {"taken_on": {"required": False}}


class TrendPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    grade = serializers.CharField(allow_blank=True)
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=Assessment.Kind.choices)
    subject = serializers.CharField(allow_blank=True)


# --- progress reports ---------------------------------------------------------------------------


class ProgressReportSerializer(BaseModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    author_name = serializers.SerializerMethodField()
    snapshot = serializers.JSONField(read_only=True)
    ai_draft_available = serializers.SerializerMethodField()

    class Meta:
        model = ProgressReport
        fields = [
            "id",
            "student",
            "student_name",
            "period",
            "period_start",
            "period_end",
            "title",
            "status",
            "summary",
            "snapshot",
            "generated_at",
            "author",
            "author_name",
            "submitted_at",
            "approved_at",
            "shared_at",
            "ai_draft_available",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.CharField())
    def get_author_name(self, obj: ProgressReport) -> str:
        return obj.author.full_name if obj.author else ""

    @extend_schema_field(serializers.BooleanField())
    def get_ai_draft_available(self, obj: ProgressReport) -> bool:
        return progress.can_draft()


class ProgressCreateSerializer(serializers.Serializer):
    student = TenantRelatedField(Student)
    period = serializers.ChoiceField(choices=ProgressReport.Period.choices, required=False)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    title = serializers.CharField(max_length=200, required=False, allow_blank=True)


class ProgressGenerateSerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=ProgressReport.Period.choices)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    students = TenantRelatedField(Student, many=True, required=False)


class ProgressGenerateResultSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    refreshed = serializers.IntegerField()
    skipped = serializers.IntegerField()


class ProgressUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    summary = serializers.CharField(max_length=20000, required=False, allow_blank=True)


class DraftSummarySerializer(serializers.Serializer):
    summary = serializers.CharField()


# --- library ------------------------------------------------------------------------------------


class LibraryItemSerializer(BaseModelSerializer):
    replacement_cost = MoneySerializerField(required=False, allow_null=True)
    available = serializers.SerializerMethodField()

    class Meta:
        model = LibraryItem
        fields = [
            "id",
            "branch",
            "name",
            "kind",
            "description",
            "identifier",
            "quantity",
            "replacement_cost",
            "location",
            "available",
            "archived_at",
            "created_at",
        ]
        read_only_fields = ["id", "archived_at", "created_at"]
        extra_kwargs = {"branch": {"required": False}, "quantity": {"min_value": 1}}

    @extend_schema_field(serializers.IntegerField())
    def get_available(self, obj: LibraryItem) -> int:
        return selectors.available(obj)


class LoanSerializer(BaseModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Loan
        fields = [
            "id",
            "item",
            "item_name",
            "student",
            "student_name",
            "status",
            "lent_on",
            "due_date",
            "returned_on",
            "notes",
            "return_notes",
            "reminded_at",
            "overdue_at",
            "overdue_notices",
            "is_overdue",
            "replacement_charged_at",
            "created_at",
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.BooleanField())
    def get_is_overdue(self, obj: Loan) -> bool:
        from ..services import org_today

        return obj.status == Loan.Status.OUT and obj.due_date < org_today()


class LoanCreateSerializer(serializers.Serializer):
    item = TenantRelatedField(LibraryItem)
    student = TenantRelatedField(Student)
    due_date = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class LoanReturnSerializer(serializers.Serializer):
    returned_on = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(max_length=500, required=False, allow_blank=True)


class LoanExtendSerializer(serializers.Serializer):
    due_date = serializers.DateField()


class LoanLostSerializer(serializers.Serializer):
    charge = serializers.BooleanField(default=False)
    amount = MoneySerializerField(required=False, allow_null=True)


# --- quizzes ------------------------------------------------------------------------------------


class ChoiceSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=20, required=False, allow_blank=True)
    text = serializers.CharField(max_length=500)


class QuestionSerializer(BaseModelSerializer):
    choices = ChoiceSerializer(many=True, required=False)
    answer = serializers.ListField(child=serializers.CharField(max_length=200), max_length=20)

    class Meta:
        model = QuizQuestion
        fields = ["id", "kind", "prompt", "choices", "answer", "points", "explanation"]
        read_only_fields = ["id"]
        extra_kwargs = {"points": {"min_value": 1, "max_value": 100}}


class QuizSerializer(BaseModelSerializer):
    subject = TenantRelatedField(Subject, required=False, allow_null=True)
    level = TenantRelatedField(Level, required=False, allow_null=True)
    questions = QuestionSerializer(many=True, required=False)
    attempts_count = serializers.SerializerMethodField()

    class Meta:
        model = Quiz
        fields = [
            "id",
            "title",
            "description",
            "subject",
            "level",
            "purpose",
            "pass_percent",
            "time_limit_minutes",
            "owner",
            "questions",
            "attempts_count",
            "archived_at",
            "created_at",
        ]
        read_only_fields = ["id", "owner", "archived_at", "created_at"]
        extra_kwargs = {"pass_percent": {"min_value": 0, "max_value": 100}}

    @extend_schema_field(serializers.IntegerField())
    def get_attempts_count(self, obj: Quiz) -> int:
        return obj.attempts.count()


class QuizAttemptSerializer(BaseModelSerializer):
    quiz_title = serializers.CharField(source="quiz.title", read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True, default="")
    marks = serializers.JSONField(read_only=True)
    answers = serializers.JSONField(read_only=True)

    class Meta:
        model = QuizAttempt
        fields = [
            "id",
            "quiz",
            "quiz_title",
            "student",
            "student_name",
            "assignment",
            "score",
            "max_score",
            "percent",
            "passed",
            "answers",
            "marks",
            "submitted_at",
        ]
        read_only_fields = fields


class PublicQuestionSerializer(serializers.Serializer):
    """A question as the learner sees it (no answers)."""

    id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=QuizQuestion.Kind.choices)
    prompt = serializers.CharField()
    choices = ChoiceSerializer(many=True)
    points = serializers.IntegerField()


# --- portal -------------------------------------------------------------------------------------


class PortalSummarySerializer(serializers.Serializer):
    homework_due = serializers.IntegerField()
    homework_overdue = serializers.IntegerField()
    resources = serializers.IntegerField()
    goals = serializers.IntegerField()
    reports = serializers.IntegerField()
    loans = serializers.IntegerField()


class PortalResourceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    description = serializers.CharField(allow_blank=True)
    kind = serializers.ChoiceField(choices=Resource.Kind.choices)
    media_type = serializers.ChoiceField(choices=Resource.MediaType.choices)
    subject = serializers.CharField(allow_blank=True)
    message = serializers.CharField(allow_blank=True)
    shared_at = serializers.DateTimeField()


class PortalResourceRef(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    media_type = serializers.ChoiceField(choices=Resource.MediaType.choices)


class PortalQuizSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    time_limit_minutes = serializers.IntegerField(allow_null=True)
    questions = PublicQuestionSerializer(many=True)


class PortalQuizResultSerializer(serializers.Serializer):
    percent = serializers.DecimalField(max_digits=5, decimal_places=2)
    passed = serializers.BooleanField()
    marks = serializers.JSONField()


class PortalHomeworkSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    instructions = serializers.CharField(allow_blank=True)
    student = serializers.UUIDField()
    student_name = serializers.CharField()
    tutor_name = serializers.CharField(allow_blank=True)
    due_at = serializers.DateTimeField()
    status = serializers.ChoiceField(choices=HomeworkAssignment.Status.choices)
    overdue = serializers.BooleanField()
    can_submit = serializers.BooleanField()
    submission_type = serializers.ChoiceField(choices=Homework.SubmissionType.choices)
    expected_minutes = serializers.IntegerField(allow_null=True)
    is_late = serializers.BooleanField()
    grade = serializers.CharField(allow_blank=True)
    feedback = serializers.CharField(allow_blank=True)
    resources = PortalResourceRef(many=True)
    attachments = FileRef(many=True)
    submissions = SubmissionSerializer(many=True)
    quiz = PortalQuizSerializer(allow_null=True)
    quiz_result = PortalQuizResultSerializer(allow_null=True)


class PortalSubmitSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000, required=False, allow_blank=True)
    link = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    files = TenantRelatedField(StoredFile, many=True, required=False)
    quiz_answers = serializers.DictField(required=False)


class PortalResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=Assessment.Kind.choices)
    subject = serializers.CharField(allow_blank=True)
    student = serializers.UUIDField()
    student_name = serializers.CharField()
    date = serializers.DateField()
    score = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True)
    max_score = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True)
    percent = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    grade = serializers.CharField(allow_blank=True)


class PortalProgressSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    student = serializers.UUIDField()
    student_name = serializers.CharField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    summary = serializers.CharField(allow_blank=True)
    snapshot = serializers.JSONField()
    shared_at = serializers.DateTimeField()


class PortalLoanSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    item = serializers.CharField()
    student_name = serializers.CharField()
    status = serializers.ChoiceField(choices=Loan.Status.choices)
    lent_on = serializers.DateField()
    due_date = serializers.DateField()
    returned_on = serializers.DateField(allow_null=True)
    is_overdue = serializers.BooleanField()
