from django.apps import AppConfig


class SitesConfig(AppConfig):
    name = "tutortrack.sites"
    label = "sites"
    verbose_name = "Website, widgets and branding"

    def ready(self) -> None:
        from tutortrack.core import branding

        from . import brand, cors, handlers, org_settings  # noqa: F401

        branding.set_provider(brand.Provider())
        cors.connect()
