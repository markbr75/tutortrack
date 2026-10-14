"""In-product sample data (FR-02-6): the sample lessons that have already happened are
completed (everyone present, so billing and pay follow), and each has a lesson report:
shared with the family, except the most recent of each job, which is still a draft."""

from __future__ import annotations

from datetime import timedelta

from django.utils.translation import gettext as _

from tutortrack.tenancy.demo import DemoContext, demo_provider


def _answers(n: int) -> dict[str, str]:
    topics = [_("Fractions and ratio"), _("Linear equations"), _("Exam technique")]
    return {
        "covered": topics[n % len(topics)],
        "homework": _("Questions 1 to 10 on the worksheet."),
        "parent_notes": _("Good focus today and steady progress."),
        "private_notes": "",
    }


@demo_provider(order=72)
def sample_delivery(ctx: DemoContext) -> None:
    from tutortrack.core.time import now
    from tutortrack.scheduling.models import Lesson

    from . import services

    past = [
        lesson
        for lesson in ctx.extras.get("lessons", [])
        if lesson.end <= now() - timedelta(hours=1) and lesson.status == Lesson.Status.PLANNED
    ]
    latest: dict[object, Lesson] = {}
    for lesson in past:
        latest[lesson.job_id] = lesson
    completed = []
    for n, lesson in enumerate(past):
        lesson = services.complete_lesson(lesson, override_balance=True)
        completed.append(lesson)
        assignment = lesson.tutors.select_related("tutor").first()
        if assignment is None:
            continue
        report = services.open_report(lesson, assignment.tutor)
        if latest.get(lesson.job_id) == lesson:
            services.save_draft(report, _answers(n), can_edit_any=True)
            continue
        services.submit_report(report, answers=_answers(n), can_edit_any=True)
        services.approve_report(report)
        services.share_report(report)
    ctx.extras["completed_lessons"] = completed
