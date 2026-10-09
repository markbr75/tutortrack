from django.apps import AppConfig


class CatalogueConfig(AppConfig):
    name = "tutortrack.catalogue"
    label = "catalogue"
    verbose_name = "Catalogue and pricing"

    def ready(self) -> None:
        from . import handlers, org_settings  # noqa: F401
