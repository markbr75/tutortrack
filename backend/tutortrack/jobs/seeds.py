"""Demo jobs (E07): one active weekly job and one seeking a tutor."""

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=60)
def jobs_demo(ctx: SeedContext) -> None:
    from tutortrack.catalogue.models import Service
    from tutortrack.jobs import services
    from tutortrack.jobs.models import Job
    from tutortrack.people.models import Student, TutorProfile

    with tenant_context(ctx.organisation):
        if Job.objects.exists():
            return
        service = Service.objects.filter(name="GCSE Maths 1:1").first()
        tutor = TutorProfile.objects.filter(email="nia.adeyemi@example.com").first()
        arjun = Student.objects.filter(first_name="Arjun").first()
        ada = Student.objects.filter(first_name="Ada").first()
        if not (service and tutor and arjun and ada):
            return
        if tutor.status != TutorProfile.Status.ACTIVE:
            from tutortrack.people.services import change_tutor_status

            change_tutor_status(tutor, TutorProfile.Status.ACTIVE)
        services.quick_setup(
            student=arjun,
            service=service,
            tutor=tutor,
            schedule=[{"weekday": 1, "time": "16:30"}],
        )
        services.quick_setup(student=ada, service=service)
        ctx.log("    created 2 demo jobs")
