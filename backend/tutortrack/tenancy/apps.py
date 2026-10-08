from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules


class TenancyConfig(AppConfig):
    name = "tutortrack.tenancy"
    label = "tenancy"
    verbose_name = "Tenancy"

    def ready(self) -> None:
        # Each app registers its organisation settings in org_settings.py (FR-02-5).
        autodiscover_modules("org_settings")
