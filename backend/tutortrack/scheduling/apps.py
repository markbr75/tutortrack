from django.apps import AppConfig


class SchedulingConfig(AppConfig):
    name = "tutortrack.scheduling"
    label = "scheduling"
    verbose_name = "Scheduling"

    def ready(self) -> None:
        from tutortrack.crm import targets
        from tutortrack.jobs import lessons as job_lessons

        from . import handlers, org_settings  # noqa: F401
        from .job_provider import SchedulingLessonsProvider
        from .models import Lesson

        targets.register("scheduling.lesson", Lesson, "scheduling.lesson.view", "Lesson")
        job_lessons.set_provider(SchedulingLessonsProvider())
