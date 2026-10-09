"""Demo schedule (E08): tutor availability, lesson series for the demo jobs, a closure."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step
from tutortrack.core.time import now


@seed_step(order=70)
def schedule_demo(ctx: SeedContext) -> None:
    from tutortrack.jobs.models import Job
    from tutortrack.people.models import TutorProfile
    from tutortrack.scheduling import services
    from tutortrack.scheduling.models import AvailabilityTemplate, CalendarEvent

    with tenant_context(ctx.organisation):
        tz = ctx.organisation.timezone
        for tutor in TutorProfile.objects.filter(status=TutorProfile.Status.ACTIVE):
            if not AvailabilityTemplate.objects.filter(tutor=tutor).exists():
                services.set_availability(
                    tutor,
                    windows=[
                        {"weekday": d, "start_time": time(15), "end_time": time(20)}
                        for d in range(5)
                    ],
                    effective_from=now().date() - timedelta(days=7),
                    timezone=tz,
                )
        for job in Job.objects.exclude(default_schedule=[]):
            services.schedule_from_job(job)
        if not CalendarEvent.objects.filter(org_wide=True).exists():
            year = now().date().year
            zone = ZoneInfo(tz)
            services.save_event(
                None,
                type=CalendarEvent.Type.HOLIDAY,
                title="Christmas closure",
                org_wide=True,
                timezone=tz,
                start=datetime(year, 12, 24, tzinfo=zone),
                end=datetime(year + 1, 1, 2, tzinfo=zone),
            )
        ctx.log("    created availability, lesson series and a closure")
