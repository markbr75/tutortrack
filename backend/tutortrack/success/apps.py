from django.apps import AppConfig


class SuccessConfig(AppConfig):
    """In-app help, product tours, the setup checklist, NPS/CSAT surveys, support chat with
    TutorTrack and consent-gated product analytics (E30 Part 2, tenant side)."""

    name = "tutortrack.success"
    label = "success"
    verbose_name = "Customer success"

    def ready(self) -> None:
        from . import handlers, notifications, org_settings  # noqa: F401 - registrations
