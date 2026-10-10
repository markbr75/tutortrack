"""Dump one organisation's data as a Django fixture (E30 FR-30-4: per-tenant restore).

Typical recovery of an accidental deletion: restore a snapshot into a scratch database,
point ``--database`` at it (a BYPASSRLS connection), dump the organisation, then load the
rows you need into staging with ``manage.py loaddata`` and copy them back through the
app's services. See ``docs/runbooks/restore-one-organisation.md``.
"""

from __future__ import annotations

import json
from typing import Any

from django.apps import apps
from django.core import serializers
from django.core.management.base import BaseCommand, CommandError

from tutortrack.core.db import PLATFORM_DB_ALIAS
from tutortrack.core.models import TenantModel


class Command(BaseCommand):
    help = "Write every row belonging to one organisation to a JSON fixture."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("slug")
        parser.add_argument("--database", default=PLATFORM_DB_ALIAS)
        parser.add_argument("--output", required=True)
        parser.add_argument("--app", action="append", default=[], help="Only these apps")

    def handle(self, *args: Any, **options: Any) -> None:
        from tutortrack.identity.models import Membership, User
        from tutortrack.tenancy.models import Organisation

        db = options["database"]
        org = Organisation.objects.using(db).filter(slug=options["slug"]).first()
        if org is None:
            raise CommandError(f"No organisation {options['slug']!r} in {db}.")
        wanted = set(options["app"])
        objects: list[Any] = [org]
        user_ids = Membership.all_tenants.using(db).filter(organisation=org).values("user_id")
        objects += list(User.objects.using(db).filter(pk__in=user_ids))
        counts: dict[str, int] = {}
        for model in apps.get_models():
            if not issubclass(model, TenantModel) or model._meta.proxy:
                continue
            if wanted and model._meta.app_label not in wanted:
                continue
            rows = list(model.all_tenants.using(db).filter(organisation=org))
            if rows:
                counts[model._meta.label] = len(rows)
                objects += rows
        data = serializers.serialize("json", objects, indent=None)
        with open(options["output"], "w") as handle:
            handle.write(data)
        self.stdout.write(json.dumps({"organisation": org.slug, "rows": counts}, indent=2))
