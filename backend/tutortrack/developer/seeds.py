"""Dev seed (E27): partner apps and a read-only demo API key for the seeded admin."""

from django.db import transaction

from tutortrack.core.context import tenant_context
from tutortrack.core.seeding import SeedContext, seed_step


@seed_step(order=995)
def developer_platform(ctx: SeedContext) -> None:
    from .models import ApiKey
    from .partners import ensure_partner_apps
    from .services import create_api_key

    with transaction.atomic():
        ensure_partner_apps()
    owner = getattr(ctx, "admin", None) or ctx.organisation.created_by
    if owner is None:
        return
    with tenant_context(ctx.organisation), transaction.atomic():
        if ApiKey.objects.filter(name="Demo read-only key").exists():
            return
        _key, secret = create_api_key(
            name="Demo read-only key",
            scopes_=["clients:read", "students:read", "lessons:read", "webhooks:read"],
            user=owner,
        )
    ctx.log(f"API key for local testing (shown once): {secret}")
