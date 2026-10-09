from django.apps import AppConfig


class DeliveryConfig(AppConfig):
    name = "tutortrack.delivery"
    label = "delivery"
    verbose_name = "Lesson delivery"

    def ready(self) -> None:
        from tutortrack.crm import targets

        from . import handlers, org_settings  # noqa: F401
        from .models import LessonReport

        targets.register(
            "delivery.lesson_report", LessonReport, "delivery.report.view", "Lesson report"
        )
