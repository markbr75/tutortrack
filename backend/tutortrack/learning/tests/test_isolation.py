"""Cross-tenant isolation for every E21 list/detail endpoint (CLAUDE.md rule 1)."""

from __future__ import annotations

from datetime import timedelta

from tutortrack.core.context import tenant_context
from tutortrack.core.testing import TenantIsolationTestMixin
from tutortrack.core.time import now
from tutortrack.learning import services
from tutortrack.learning.models import GradeScale, HomeworkAssignment, LessonTopic, ResourceFolder
from tutortrack.people.tests.factories import StudentFactory

from .factories import (
    AssessmentFactory,
    CurriculumFactory,
    GoalFactory,
    LibraryItemFactory,
    ProgressReportFactory,
    QuestionFactory,
    QuizFactory,
    ResourceFactory,
    TopicFactory,
)


def _homework(org):
    student = StudentFactory(organisation=org)
    with tenant_context(org):
        return services.assign_homework(
            title="HW", due_at=now() + timedelta(days=2), students=[student]
        )


class TestResources(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/resources"

    def make_object(self, organisation):
        return ResourceFactory(organisation=organisation)


class TestFolders(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/folders"

    def make_object(self, organisation):
        with tenant_context(organisation):
            return ResourceFolder.objects.create(name="Maths")


class TestShares(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/resource-shares"

    def make_object(self, organisation):
        resource = ResourceFactory(organisation=organisation)
        with tenant_context(organisation):
            return services.share_resource(
                resource, students=[StudentFactory(organisation=organisation)]
            )[0]

    def test_detail_of_other_organisation_is_404(self, org, other_org):
        """Shares have no detail endpoint; deleting another tenant's share is a 404."""
        from tutortrack.core.testing import client_for

        theirs = self.make_object(other_org)
        response = client_for(org, self.acting_user(org)).delete(f"{self.list_url}/{theirs.pk}")
        assert response.status_code == 404


class TestGradeScales(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/grade-scales"

    def make_object(self, organisation):
        with tenant_context(organisation):
            services.ensure_default_scales()
            return GradeScale.objects.filter(is_default=True).get()


class TestHomework(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/homework"

    def make_object(self, organisation):
        return _homework(organisation)


class TestAssignments(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/homework-assignments"

    def make_object(self, organisation):
        homework = _homework(organisation)
        with tenant_context(organisation):
            return HomeworkAssignment.objects.get(homework=homework)


class TestCurricula(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/curricula"

    def make_object(self, organisation):
        return CurriculumFactory(organisation=organisation)


class TestNodes(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/curriculum-nodes"

    def make_object(self, organisation):
        return TopicFactory(organisation=organisation)


class TestLessonTopics(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/lesson-topics"

    def make_object(self, organisation):
        from tutortrack.catalogue.tests.factories import ServiceFactory
        from tutortrack.scheduling import services as scheduling

        node = TopicFactory(organisation=organisation)
        service = ServiceFactory(organisation=organisation)
        start = (now() + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
        with tenant_context(organisation):
            lesson = scheduling.create_lesson(
                start=start,
                end=start + timedelta(hours=1),
                service=service,
                attendees=[{"student": StudentFactory(organisation=organisation)}],
                timezone="Europe/London",
                override_conflicts=True,
            ).lesson
            return LessonTopic.objects.create(lesson=lesson, node=node)

    def test_detail_of_other_organisation_is_404(self, org, other_org):
        from tutortrack.core.testing import client_for

        theirs = self.make_object(other_org)
        response = client_for(org, self.acting_user(org)).delete(f"{self.list_url}/{theirs.pk}")
        assert response.status_code == 404


class TestMastery(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/mastery"

    def make_object(self, organisation):
        node = TopicFactory(organisation=organisation)
        with tenant_context(organisation):
            return services.set_mastery(StudentFactory(organisation=organisation), node, "secure")

    def test_detail_of_other_organisation_is_404(self, org, other_org):
        """Mastery is listed per student; another tenant's student is a 404 there."""
        from tutortrack.core.testing import client_for

        theirs = self.make_object(other_org)
        url = f"/api/v1/learning/students/{theirs.student_id}/coverage"
        assert client_for(org, self.acting_user(org)).get(url).status_code == 404


class TestGoals(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/goals"

    def make_object(self, organisation):
        return GoalFactory(organisation=organisation)


class TestAssessments(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/assessments"

    def make_object(self, organisation):
        return AssessmentFactory(organisation=organisation)


class TestResults(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/assessment-results"

    def make_object(self, organisation):
        assessment = AssessmentFactory(organisation=organisation)
        with tenant_context(organisation):
            return services.record_result(
                assessment=assessment, student=StudentFactory(organisation=organisation)
            )


class TestProgressReports(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/progress-reports"

    def make_object(self, organisation):
        return ProgressReportFactory(organisation=organisation)


class TestLibraryItems(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/library-items"

    def make_object(self, organisation):
        return LibraryItemFactory(organisation=organisation)


class TestLoans(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/loans"

    def make_object(self, organisation):
        item = LibraryItemFactory(organisation=organisation)
        with tenant_context(organisation):
            return services.lend(item, StudentFactory(organisation=organisation))


class TestQuizzes(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/quizzes"

    def make_object(self, organisation):
        return QuestionFactory(organisation=organisation).quiz


class TestQuizAttempts(TenantIsolationTestMixin):
    list_url = "/api/v1/learning/quiz-attempts"

    def make_object(self, organisation):
        quiz = QuizFactory(organisation=organisation)
        QuestionFactory(organisation=organisation, quiz=quiz)
        with tenant_context(organisation):
            return services.take_quiz(
                quiz, answers={}, student=StudentFactory(organisation=organisation)
            )
