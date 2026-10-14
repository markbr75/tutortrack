"""Demo AI settings (E31): every AI feature turned on for the demo organisation, so the
"Draft with AI" buttons, command bar and copilot work locally. Without
``ANTHROPIC_API_KEY`` they answer from the deterministic fake provider."""

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=85)
def ai_demo(ctx: SeedContext) -> None:
    from tutortrack.ai import services
    from tutortrack.ai.models import AIFeatureSetting, Feature

    with tenant_context(ctx.organisation):
        if AIFeatureSetting.objects.exists():
            return
        for feature in Feature.values:
            services.update_feature(feature, enabled=True)
    ctx.log("    turned on the AI assistant features")
