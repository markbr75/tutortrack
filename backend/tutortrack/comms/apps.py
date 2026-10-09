from django.apps import AppConfig


class CommsConfig(AppConfig):
    name = "tutortrack.comms"
    label = "comms"
    verbose_name = "Communications"

    def ready(self) -> None:
        from tutortrack.crm import selectors as crm

        from . import catalogue, handlers, org_settings  # noqa: F401
        from .selectors import message_timeline

        crm.register_timeline_provider("message", message_timeline)
