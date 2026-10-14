"""In-product sample data (FR-02-6): homework set by a sample tutor and a target-grade goal
with milestones."""

from __future__ import annotations

from datetime import datetime, time, timedelta

from django.utils.translation import gettext as _

from tutortrack.tenancy.demo import DemoContext, demo_provider


@demo_provider(order=80)
def sample_learning(ctx: DemoContext) -> None:
    from . import services

    students = ctx.extras.get("students", {})
    tutors = ctx.extras.get("tutors", {})
    arjun, ada = students.get("Arjun"), students.get("Ada")
    if arjun is not None:
        due = datetime.combine(
            services.org_today() + timedelta(days=5), time(18), tzinfo=services.org_zone()
        )
        services.assign_homework(
            title=_("Fractions worksheet"),
            instructions=_("Questions 1 to 10. Show your working."),
            due_at=due,
            students=[arjun],
            set_by=tutors.get("Nia"),
            submission_type="text",
            expected_minutes=30,
        )
    if ada is not None:
        services.save_goal(
            None,
            student=ada,
            kind="target_grade",
            title=_("Grade A in A-level Physics"),
            target_grade="A",
            current_grade="B",
            exam_date=services.org_today() + timedelta(days=240),
            milestones=[
                {"title": _("Mechanics topic test above 70%"), "done": True},
                {"title": _("Electricity secure")},
                {"title": _("Full past paper under timed conditions")},
            ],
        )
