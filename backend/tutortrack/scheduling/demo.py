"""In-product sample data (FR-02-6): the sample jobs' weekly lesson series (about seven
weeks: three past, four ahead), expanded in the organisation's timezone."""

from __future__ import annotations

from tutortrack.tenancy.demo import DemoContext, demo_provider


@demo_provider(order=70)
def sample_lessons(ctx: DemoContext) -> None:
    from . import services
    from .models import Lesson

    jobs = ctx.extras.get("jobs", [])
    for job in jobs:
        services.schedule_from_job(job)
    # Series expand with bulk_create (no save signal), so track the lessons explicitly.
    lessons = list(Lesson.objects.filter(job__in=jobs).order_by("start"))
    ctx.track_all(lessons)
    ctx.extras["lessons"] = lessons
