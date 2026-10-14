"""In-product sample data (FR-02-6): three weekly 1:1 jobs that started three weeks ago and
run for four more weeks, at fixed local times (E08 turns them into lesson series)."""

from __future__ import annotations

from datetime import timedelta

from tutortrack.tenancy.demo import DemoContext, demo_provider

# (student, tutor, weekday (Monday = 0), local time)
JOBS = [("Arjun", "Nia", 1, "16:30"), ("Maya", "Nia", 2, "16:00"), ("Ada", "Sam", 3, "17:00")]


@demo_provider(order=60)
def sample_jobs(ctx: DemoContext) -> None:
    from tutortrack.billing.services import org_today

    from . import services

    service = ctx.extras.get("services", {}).get("one_to_one")
    students, tutors = ctx.extras.get("students", {}), ctx.extras.get("tutors", {})
    if service is None:
        return
    today = org_today()
    jobs = []
    for student, tutor, weekday, at in JOBS:
        if student not in students or tutor not in tutors:
            continue
        jobs.append(
            services.quick_setup(
                student=students[student],
                service=service,
                tutor=tutors[tutor],
                schedule=[{"weekday": weekday, "time": at}],
                start_date=today - timedelta(days=21),
                expected_end_date=today + timedelta(days=28),
            )
        )
    ctx.extras["jobs"] = jobs
