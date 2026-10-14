"""``manage.py mobile_app_config [--org <slug>] [--out white-label.json]``: the native app
shell configuration (E16-T11) for an organisation's white-label build, or the generic app
without ``--org``. ``frontend/apps/mobile/scripts/configure.mjs`` reads the file."""

from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser


class Command(BaseCommand):
    help = "Write the Capacitor white-label configuration for an organisation (E16-T11)."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--org", default="", help="Organisation slug (default: generic app)")
        parser.add_argument("--out", default="", help="File to write (default: stdout)")
        parser.add_argument(
            "--require-white-label",
            action="store_true",
            help="Fail unless the organisation's plan includes white-label apps.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.sites import mobile
        from tutortrack.tenancy.models import Organisation

        if options["org"]:
            organisation = Organisation.objects.filter(slug=options["org"]).first()
            if organisation is None:
                raise CommandError(f"No organisation {options['org']!r}.")
            config = mobile.app_config(organisation)
            if options["require_white_label"] and not config["white_label"]:
                raise CommandError("This organisation's plan has no white-label apps.")
        else:
            config = mobile.generic_config()
        text = json.dumps(config, indent=2) + "\n"
        if options["out"]:
            with open(options["out"], "w", encoding="utf-8") as handle:
                handle.write(text)
            self.stdout.write(f"Wrote {options['out']} ({config['appId']}).")
        else:
            self.stdout.write(text)
