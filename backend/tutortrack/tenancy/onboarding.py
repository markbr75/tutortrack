"""Onboarding wizard state machine (FR-02-6 step 2, E02-T07).

Steps are skippable and can be revisited; progress is saved after each one. Each step
validates its payload, applies what tenancy owns (organisation profile, branding,
settings, feature defaults) and records the payload. Steps owned by epics that are not
built yet (first service → E06, tutor invites → E03, first student → E05, payments → E11)
are stored and announced with ``onboarding.step_completed`` so those epics' handlers can
act on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar

from django.db import transaction
from django.utils.translation import gettext as _
from rest_framework import serializers

from tutortrack.core import audit, flags
from tutortrack.core.api.serializers import MoneySerializerField
from tutortrack.core.context import require_organisation_id
from tutortrack.core.events import DomainEvent, publish
from tutortrack.core.events.base import to_json_safe
from tutortrack.core.exceptions import BusinessRuleViolation, NotFound
from tutortrack.core.time import is_valid_timezone, now

from . import services, settings_service
from .models import OnboardingState, Organisation

# --- events ---------------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class OnboardingStepCompleted(DomainEvent):
    event_type: ClassVar[str] = "onboarding.step_completed"
    subject_type: ClassVar[str] = "organisation"

    step: str
    skipped: bool
    answers: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class OnboardingCompleted(DomainEvent):
    event_type: ClassVar[str] = "onboarding.completed"
    subject_type: ClassVar[str] = "organisation"

    skipped_steps: list[str] = field(default_factory=list)


# --- step payloads --------------------------------------------------------------------------------


class BusinessStep(serializers.Serializer):
    business_type = serializers.ChoiceField(choices=Organisation.BusinessType.choices)
    team_size = serializers.ChoiceField(
        choices=["1", "2-5", "6-20", "21-100", "100+"], required=False
    )


class LocaleStep(serializers.Serializer):
    locale = serializers.ChoiceField(choices=["en-GB", "en-US"])
    default_currency = serializers.CharField(max_length=3)
    timezone = serializers.CharField(max_length=64)
    week_start_day = serializers.ChoiceField(choices=Organisation.Weekday.choices, required=False)

    def validate_timezone(self, value: str) -> str:
        if not is_valid_timezone(value):
            raise serializers.ValidationError(_("Unknown timezone."))
        return value

    def validate_default_currency(self, value: str) -> str:
        from tutortrack.core.money import validate_currency

        try:
            return validate_currency(value.upper())
        except ValueError as exc:
            raise serializers.ValidationError(_("Unknown currency.")) from exc


class BrandingStep(serializers.Serializer):
    logo = serializers.UUIDField(required=False, allow_null=True)
    primary_colour = serializers.RegexField(r"^#[0-9a-fA-F]{6}$", required=False)


class ServiceStep(serializers.Serializer):
    subject = serializers.CharField(max_length=100)
    level = serializers.CharField(max_length=100, required=False, allow_blank=True)
    duration_minutes = serializers.IntegerField(min_value=5, max_value=480)
    price = MoneySerializerField()

    def validate_price(self, value: Any) -> Any:
        if value.amount <= Decimal(0):
            raise serializers.ValidationError(_("Enter a price above zero."))
        return value


class TutorsStep(serializers.Serializer):
    emails = serializers.ListField(child=serializers.EmailField(), max_length=50)


class StudentStep(serializers.Serializer):
    student_first_name = serializers.CharField(max_length=100)
    student_last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    contact_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    import_csv = serializers.BooleanField(default=False)


class PaymentsStep(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["stripe", "later"])


class InvoicingStep(serializers.Serializer):
    invoicing_style = serializers.ChoiceField(choices=["payg", "monthly_advance", "packages"])


@dataclass(frozen=True)
class Step:
    key: str
    payload: type[serializers.Serializer]
    multi_only: bool = False  # only for teams/agencies (FR-02-6 "agency/team only")


STEPS: tuple[Step, ...] = (
    Step("business", BusinessStep),
    Step("locale", LocaleStep),
    Step("branding", BrandingStep),
    Step("service", ServiceStep),
    Step("tutors", TutorsStep, multi_only=True),
    Step("students", StudentStep),
    Step("payments", PaymentsStep),
    Step("invoicing", InvoicingStep),
)
STEP_KEYS = tuple(s.key for s in STEPS)

# Business types that get the multi-branch feature on by default (still plan-gated in E04).
MULTI_BRANCH_TYPES = {Organisation.BusinessType.AGENCY, Organisation.BusinessType.CENTRE}


# --- state machine --------------------------------------------------------------------------------


def applicable_steps(organisation: Organisation) -> list[str]:
    multi = organisation.mode == Organisation.Mode.MULTI
    return [s.key for s in STEPS if multi or not s.multi_only]


def _next_step(state: OnboardingState, organisation: Organisation) -> str:
    done = set(state.completed_steps) | set(state.skipped_steps)
    return next((k for k in applicable_steps(organisation) if k not in done), "")


def _organisation() -> Organisation:
    return Organisation.objects.get(pk=require_organisation_id())


def start_onboarding(organisation: Organisation) -> OnboardingState:
    state, _ = OnboardingState.objects.get_or_create(
        organisation=organisation, defaults={"current_step": STEP_KEYS[0]}
    )
    return state


def get_state() -> OnboardingState:
    return start_onboarding(_organisation())


def _apply(step: str, data: dict[str, Any], organisation: Organisation) -> dict[str, Any]:
    """Apply what tenancy owns; return the JSON-safe payload to record."""
    if step == "business":
        services.update_organisation(organisation, business_type=data["business_type"])
        if data["business_type"] in MULTI_BRANCH_TYPES:
            flags.set_override(
                "multi_branch", organisation.pk, enabled=True, reason="onboarding default"
            )
    elif step == "locale":
        services.update_organisation(organisation, **data)
    elif step == "branding":
        changes: dict[str, Any] = {}
        if "primary_colour" in data:
            changes["primary_colour"] = data["primary_colour"]
        if "logo" in data:
            from tutortrack.core.models import StoredFile

            logo = None
            if data["logo"] is not None:
                logo = StoredFile.objects.filter(pk=data["logo"]).first()
                if logo is None:
                    raise BusinessRuleViolation(
                        _("Upload the logo first."), extra={"errors": {"logo": ["not found"]}}
                    )
            changes["logo"] = logo
        if changes:
            services.update_organisation(organisation, **changes)
    elif step == "invoicing":
        settings_service.update_settings(
            "billing", {"billing.invoicing_style": data["invoicing_style"]}
        )
    payload = dict(data)
    if step == "service":
        payload["price"] = MoneySerializerField().to_representation(data["price"])
    recorded: dict[str, Any] = to_json_safe(payload)
    return recorded


@transaction.atomic
def submit_step(step: str, payload: dict[str, Any], *, skip: bool = False) -> OnboardingState:
    if step not in STEP_KEYS:
        raise NotFound(f"Unknown onboarding step {step!r}.")
    organisation = _organisation()
    state = OnboardingState.objects.select_for_update().get_or_create(organisation=organisation)[0]
    if state.completed_at is not None:
        raise BusinessRuleViolation(_("Onboarding is already complete."))
    if step not in applicable_steps(organisation):
        raise BusinessRuleViolation(_("This step does not apply to your business type."))

    recorded: dict[str, Any] = {}
    if not skip:
        definition = next(s for s in STEPS if s.key == step)
        serializer = definition.payload(data=payload)
        serializer.is_valid(raise_exception=True)
        recorded = _apply(step, dict(serializer.validated_data), organisation)
        organisation.refresh_from_db()

    with audit.track(state, action="onboarding_step"):
        completed = [s for s in state.completed_steps if s != step]
        skipped = [s for s in state.skipped_steps if s != step]
        (skipped if skip else completed).append(step)
        state.completed_steps, state.skipped_steps = completed, skipped
        state.data = {**state.data, step: recorded} if not skip else state.data
        state.current_step = _next_step(state, organisation)
        state.save()
    publish(
        OnboardingStepCompleted(
            subject_id=organisation.pk, step=step, skipped=skip, answers=recorded
        )
    )
    return state


@transaction.atomic
def complete() -> OnboardingState:
    """Finish the wizard (remaining steps count as skipped)."""
    organisation = _organisation()
    state = OnboardingState.objects.select_for_update().get_or_create(organisation=organisation)[0]
    if state.completed_at is not None:
        return state
    done = set(state.completed_steps) | set(state.skipped_steps)
    with audit.track(state, action="onboarding_complete"):
        state.skipped_steps = [
            *state.skipped_steps,
            *[k for k in applicable_steps(organisation) if k not in done],
        ]
        state.current_step = ""
        state.completed_at = now()
        state.save()
    publish(OnboardingCompleted(subject_id=organisation.pk, skipped_steps=state.skipped_steps))
    return state
