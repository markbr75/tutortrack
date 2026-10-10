"""Fetch today's exchange rates now (the Beat task does this daily)."""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fetch the latest exchange rates into FxRate."

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.reporting.fx import fetch_latest

        self.stdout.write(f"{fetch_latest()} rates stored")
