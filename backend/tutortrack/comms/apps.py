from django.apps import AppConfig


class CommsConfig(AppConfig):
    name = "tutortrack.comms"
    label = "comms"
    verbose_name = "Communications"

    def ready(self) -> None:
        from tutortrack.core.storage.services import register_access_rule
        from tutortrack.crm import selectors as crm

        from . import (  # noqa: F401
            account_emails,
            catalogue,
            digests,
            events,
            g4_types,
            handlers,
            marketing_providers,
            org_settings,
            phase2_types,
            students,
        )
        from .selectors import may_open_broadcast_file, may_open_thread_file, message_timeline

        crm.register_timeline_provider("message", message_timeline)
        register_access_rule("comms.threadmessage", may_open_thread_file)
        register_access_rule("comms.broadcast", may_open_broadcast_file)
