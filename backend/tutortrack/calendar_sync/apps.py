from django.apps import AppConfig


class CalendarSyncConfig(AppConfig):
    name = "tutortrack.calendar_sync"
    label = "calendar_sync"
    verbose_name = "Calendar sync and online meetings"

    def ready(self) -> None:
        from tutortrack.scheduling import external

        from . import handlers  # noqa: F401
        from .meetings import join_resolver
        from .selectors import tutor_busy

        external.register_busy_source(tutor_busy)
        external.register_join_resolver(join_resolver)
