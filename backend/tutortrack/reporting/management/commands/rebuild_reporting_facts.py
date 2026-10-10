"""Recompute the reporting fact tables for one or every organisation (backfill, repair)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from tutortrack.core.context import tenant_context
from tutortrack.tenancy.models import Organisation


class Command(BaseCommand):
    help = "Rebuild reporting facts and daily aggregates (all organisations, or --org slug)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--org", help="Organisation slug")

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.reporting import facts

        orgs = Organisation.objects.all()
        if options.get("org"):
            orgs = orgs.filter(slug=options["org"])
        for org in orgs:
            with tenant_context(org):
                counts = facts.rebuild()
            self.stdout.write(f"{org.slug}: {counts}")
