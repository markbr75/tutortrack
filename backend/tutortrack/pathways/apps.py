from django.apps import AppConfig


class PathwaysConfig(AppConfig):
    name = "tutortrack.pathways"
    label = "pathways"
    verbose_name = "Pathways"

    def ready(self) -> None:
        from django.utils.module_loading import autodiscover_modules

        from . import (  # noqa: F401
            automations,
            builtin_pathways,
            notifications,
            org_settings,
            pathway_steps,
        )

        autodiscover_modules("pathway_steps")  # step types from other apps (E34 T02 on)
        builtin_pathways.discover()
