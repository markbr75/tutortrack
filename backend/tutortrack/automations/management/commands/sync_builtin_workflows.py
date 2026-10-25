"""Install the built-in workflows each organisation is missing and move unedited ones to
newer defaults (E33 FR-33-2). Idempotent; the Temporal worker task runs it before polling
(infra/terraform/ecs.tf), like ``ensure_platform_schedules``."""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Install and upgrade the built-in workflows for every organisation."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organisation", help="Only this organisation (id or slug)")

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.automations.services import install_builtins
        from tutortrack.core.context import tenant_context
        from tutortrack.tenancy.models import Organisation

        orgs = Organisation.objects.exclude(status=Organisation.Status.CANCELLED)
        if options.get("organisation"):
            ref = options["organisation"]
            orgs = orgs.filter(pk=ref) if _is_uuid(ref) else orgs.filter(slug=ref)
        installed = upgraded = 0
        for org in orgs.order_by("created_at"):
            with tenant_context(org.pk):
                counts = install_builtins()
            installed += counts["installed"]
            upgraded += counts["upgraded"]
        self.stdout.write(f"Built-in workflows: {installed} installed, {upgraded} upgraded.")


def _is_uuid(value: str) -> bool:
    import uuid

    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True
