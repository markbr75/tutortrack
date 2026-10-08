"""Read and write registered settings (FR-02-5). See ``settings_registry`` for definitions."""

from __future__ import annotations

import copy
from typing import Any

from django.db import transaction
from rest_framework import serializers

from tutortrack.core import audit
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import publish
from tutortrack.core.exceptions import BusinessRuleViolation

from . import events
from .models import Branch, BranchSettings, Organisation, OrganisationSettings
from .settings_registry import SettingDefinition, registry


def ensure_settings_rows(organisation: Organisation) -> OrganisationSettings:
    row, _ = OrganisationSettings.objects.get_or_create(organisation=organisation)
    return row


def _org_values() -> dict[str, Any]:
    row = OrganisationSettings.objects.filter(organisation_id=require_organisation_id()).first()
    return dict(row.values) if row else {}


def _branch_values(branch: Branch | None) -> dict[str, Any]:
    if branch is None:
        return {}
    row = BranchSettings.objects.filter(branch=branch).first()
    return dict(row.values) if row else {}


def _resolve(definition: SettingDefinition, org: dict[str, Any], branch: dict[str, Any]) -> Any:
    if definition.scope == "branch" and definition.key in branch:
        return copy.deepcopy(branch[definition.key])
    if definition.key in org:
        return copy.deepcopy(org[definition.key])
    return copy.deepcopy(definition.default)


def get_setting(key: str, *, branch: Branch | None = None) -> Any:
    """The effective value for the organisation in context (and ``branch``, if given)."""
    return _resolve(registry.get(key), _org_values(), _branch_values(branch))


def area_values(area: str, *, branch: Branch | None = None) -> dict[str, Any]:
    org, br = _org_values(), _branch_values(branch)
    return {d.key: _resolve(d, org, br) for d in registry.area(area)}


def branch_overrides(area: str, branch: Branch) -> list[str]:
    values = _branch_values(branch)
    return [d.key for d in registry.area(area) if d.scope == "branch" and d.key in values]


@transaction.atomic
def update_settings(
    area: str, changes: dict[str, Any], *, branch: Branch | None = None
) -> dict[str, Any]:
    """Validate and store ``changes`` (``{key: value}``) for an area.

    At organisation level ``None`` resets a key to its default. At branch level only
    ``scope="branch"`` keys are accepted and ``None`` removes the branch override.
    Emits ``organisation.settings_updated`` when anything changed.
    """
    definitions = {d.key: d for d in registry.area(area)}
    if not definitions:
        raise BusinessRuleViolation(f"Unknown settings area {area!r}.")
    errors: dict[str, Any] = {}
    cleaned: dict[str, Any] = {}
    for key, value in changes.items():
        definition = definitions.get(key)
        if definition is None:
            errors[key] = ["Unknown setting."]
            continue
        if branch is not None and definition.scope != "branch":
            errors[key] = ["This setting cannot be overridden per branch."]
            continue
        if value is None:
            cleaned[key] = None
            continue
        try:
            cleaned[key] = definition.clean(value)
        except serializers.ValidationError as exc:
            errors[key] = exc.detail
    if errors:
        raise serializers.ValidationError(errors)

    if branch is None:
        row = OrganisationSettings.objects.select_for_update().get_or_create(
            organisation_id=require_organisation_id()
        )[0]
    else:
        row = BranchSettings.objects.select_for_update().get_or_create(branch=branch)[0]

    with audit.track(row, action="update_settings") as tracker:
        values = dict(row.values)
        for key, value in cleaned.items():
            if value is None:
                values.pop(key, None)
            else:
                values[key] = value
        row.values = values
        row.save()
    if tracker.entry is not None:
        changed = sorted(k for k in cleaned if tracker.before["values"].get(k) != values.get(k))
        publish(
            events.OrganisationSettingsUpdated(
                subject_id=require_organisation_id(),
                area=area,
                branch_id=str(branch.pk) if branch else None,
                keys=changed,
            ),
            branch_id=branch.pk if branch else None,
        )
    return area_values(area, branch=branch)
