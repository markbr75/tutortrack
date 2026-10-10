from django.apps import AppConfig


class PayrollConfig(AppConfig):
    name = "tutortrack.payroll"
    label = "payroll"
    verbose_name = "Payroll"

    def ready(self) -> None:
        from . import handlers, org_settings  # noqa: F401
