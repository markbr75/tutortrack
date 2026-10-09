from django.apps import AppConfig


class JobsConfig(AppConfig):
    name = "tutortrack.jobs"
    label = "jobs"
    verbose_name = "Jobs"

    def ready(self) -> None:
        from tutortrack.crm import targets

        from . import org_settings  # noqa: F401
        from .models import Job

        targets.register("jobs.job", Job, "jobs.job.view", "Job")
