"""Install the ready-made pathways each organisation is missing and move unedited ones to
newer defaults (E34 FR-34-1). Idempotent; the Temporal worker task runs it before polling,
after ``sync_builtin_workflows``."""

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Install and upgrade the ready-made pathways for every organisation."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--organisation", help="Only this organisation (slug)")

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.core.context import tenant_context
        from tutortrack.pathways.services import install_builtins
        from tutortrack.tenancy.models import Organisation

        orgs = Organisation.objects.exclude(status=Organisation.Status.CANCELLED)
        if options.get("organisation"):
            orgs = orgs.filter(slug=options["organisation"])
        installed = upgraded = 0
        for org in orgs.order_by("created_at"):
            with tenant_context(org.pk):
                counts = install_builtins()
            installed += counts["installed"]
            upgraded += counts["upgraded"]
        self.stdout.write(f"Ready-made pathways: {installed} installed, {upgraded} upgraded.")
