from django.apps import AppConfig


class AIConfig(AppConfig):
    name = "tutortrack.ai"
    label = "ai"
    verbose_name = "AI assistant"

    def ready(self) -> None:
        from tutortrack.learning import progress

        from . import handlers, org_settings  # noqa: F401
        from .features import progress as ai_progress

        # E21 seam: "Draft with AI" on progress reports (FR-31-2).
        progress.register_drafter(ai_progress.drafter, ai_progress.available)
