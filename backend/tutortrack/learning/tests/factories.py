from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import factory

from tutortrack.core.tests.factories import TenantFactory
from tutortrack.learning.models import (
    Assessment,
    Curriculum,
    CurriculumNode,
    Goal,
    LibraryItem,
    ProgressReport,
    Quiz,
    QuizQuestion,
    Resource,
)
from tutortrack.people.tests.factories import StudentFactory


class ResourceFactory(TenantFactory):
    class Meta:
        model = Resource

    title = factory.Sequence(lambda n: f"Resource {n}")
    kind = Resource.Kind.LINK
    url = "https://example.com/worksheet"
    media_type = Resource.MediaType.LINK
    visibility = Resource.Visibility.TUTORS


class CurriculumFactory(TenantFactory):
    class Meta:
        model = Curriculum

    name = factory.Sequence(lambda n: f"Curriculum {n}")


class UnitFactory(TenantFactory):
    class Meta:
        model = CurriculumNode

    curriculum = factory.SubFactory(
        CurriculumFactory, organisation=factory.SelfAttribute("..organisation")
    )
    kind = CurriculumNode.Kind.UNIT
    name = factory.Sequence(lambda n: f"Unit {n}")


class TopicFactory(TenantFactory):
    class Meta:
        model = CurriculumNode

    parent = factory.SubFactory(UnitFactory, organisation=factory.SelfAttribute("..organisation"))
    curriculum = factory.SelfAttribute("parent.curriculum")
    kind = CurriculumNode.Kind.TOPIC
    name = factory.Sequence(lambda n: f"Topic {n}")


class GoalFactory(TenantFactory):
    class Meta:
        model = Goal

    student = factory.SubFactory(
        StudentFactory, organisation=factory.SelfAttribute("..organisation")
    )
    branch_id = factory.SelfAttribute("student.branch_id")
    title = factory.Sequence(lambda n: f"Goal {n}")


class AssessmentFactory(TenantFactory):
    class Meta:
        model = Assessment

    name = factory.Sequence(lambda n: f"Mock {n}")
    kind = Assessment.Kind.MOCK_EXAM
    held_on = factory.LazyFunction(date.today)
    max_score = Decimal("80")


class ProgressReportFactory(TenantFactory):
    class Meta:
        model = ProgressReport

    student = factory.SubFactory(
        StudentFactory, organisation=factory.SelfAttribute("..organisation")
    )
    branch_id = factory.SelfAttribute("student.branch_id")
    period_start = factory.LazyFunction(lambda: date.today() - timedelta(days=30))
    period_end = factory.LazyFunction(date.today)
    title = "Progress report"


class LibraryItemFactory(TenantFactory):
    class Meta:
        model = LibraryItem

    name = factory.Sequence(lambda n: f"Book {n}")
    currency = "GBP"
    replacement_cost_amount = Decimal("9.99")
    quantity = 2


class QuizFactory(TenantFactory):
    class Meta:
        model = Quiz

    title = factory.Sequence(lambda n: f"Quiz {n}")


class QuestionFactory(TenantFactory):
    class Meta:
        model = QuizQuestion

    quiz = factory.SubFactory(QuizFactory, organisation=factory.SelfAttribute("..organisation"))
    kind = QuizQuestion.Kind.SINGLE
    prompt = "Which is half?"
    choices = [{"id": "a", "text": "2/4"}, {"id": "b", "text": "2/3"}]
    answer = ["a"]
