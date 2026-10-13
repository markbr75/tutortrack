from django.apps import AppConfig


class CoursesConfig(AppConfig):
    name = "tutortrack.courses"
    label = "courses"
    verbose_name = "Courses, classes and terms"

    def ready(self) -> None:
        from . import handlers, hooks, notifications, org_settings, widgets  # noqa: F401
