from django.apps import AppConfig


class GrowthConfig(AppConfig):
    name = "tutortrack.growth"
    label = "growth"
    verbose_name = "Reviews, referrals and affiliates"

    def ready(self) -> None:
        from . import handlers, hooks, notifications, org_settings  # noqa: F401
