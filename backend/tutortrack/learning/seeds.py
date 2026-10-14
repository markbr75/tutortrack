"""Demo learning data (E21): GCSE Maths installed, a shared resource, homework, a goal
with milestones, a mock exam result and a lending library item on loan."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from tutortrack.core.context import tenant_context
from tutortrack.core.money import Money
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=80)
def learning_demo(ctx: SeedContext) -> None:
    from tutortrack.learning import services
    from tutortrack.learning.models import Curriculum
    from tutortrack.people.models import Student, TutorProfile

    with tenant_context(ctx.organisation):
        if Curriculum.objects.exists():
            return
        student = (
            Student.objects.filter(status=Student.Status.ACTIVE).order_by("created_at").first()
        )
        tutor = TutorProfile.objects.filter(status=TutorProfile.Status.ACTIVE).first()
        maths = services.install_builtin("gcse-maths")
        services.install_builtin("ks2-english")
        services.ensure_default_scales()
        resource = services.save_resource(
            None,
            title="Equivalent fractions explained",
            kind="link",
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            tags=["fractions"],
            visibility="tutors",
            topics=list(maths.nodes.filter(name="Fractions")),
        )
        if student is None:
            ctx.log("    installed curricula (no students for the rest)")
            return
        services.share_resource(resource, students=[student], message="Watch before Tuesday.")
        zone = services.org_zone()
        due = datetime.combine(services.org_today() + timedelta(days=5), time(18), tzinfo=zone)
        services.assign_homework(
            title="Fractions worksheet",
            instructions="Questions 1 to 10. Show your working.",
            due_at=due,
            students=[student],
            set_by=tutor,
            submission_type="text",
            expected_minutes=30,
            resources=[resource],
        )
        services.save_goal(
            None,
            student=student,
            kind="target_grade",
            title="Grade 7 in GCSE Maths",
            target_grade="7",
            current_grade="5",
            exam_date=services.org_today() + timedelta(days=240),
            milestones=[
                {"title": "Grade 6 in the mock exam", "done": True},
                {"title": "Algebra secure"},
                {"title": "Full past paper under timed conditions"},
            ],
        )
        mock = services.save_assessment(
            None,
            name="Autumn mock (paper 1)",
            kind="mock_exam",
            held_on=services.org_today() - timedelta(days=14),
            max_score=Decimal("80"),
        )
        services.record_result(assessment=mock, student=student, score=Decimal("54"), grade="6")
        item = services.save_item(
            None,
            name="CGP GCSE Maths revision guide",
            kind="book",
            identifier="9781782945628",
            quantity=3,
            replacement_cost=Money(Decimal("7.99"), ctx.organisation.default_currency),
        )
        services.lend(item, student)
        ctx.log("    installed curricula and added homework, a goal, a result and a loan")
