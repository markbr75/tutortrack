"""Onboarding wizard API (E02-T07)."""

from __future__ import annotations

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.context import require_organisation_id
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from .. import onboarding
from .. import permissions as perms
from ..models import OnboardingState, Organisation


class OnboardingStepStatusSerializer(serializers.Serializer):
    key = serializers.CharField()
    status = serializers.ChoiceField(choices=["pending", "completed", "skipped"])


class OnboardingStateSerializer(serializers.Serializer):
    current_step = serializers.CharField(allow_blank=True)
    steps = OnboardingStepStatusSerializer(many=True)
    answers = serializers.DictField(
        child=serializers.JSONField(), help_text="Saved answers per completed step."
    )
    completed_at = serializers.DateTimeField(allow_null=True)


def state_payload(state: OnboardingState) -> dict[str, Any]:
    organisation = Organisation.objects.get(pk=require_organisation_id())
    steps = []
    for key in onboarding.applicable_steps(organisation):
        status = (
            "completed"
            if key in state.completed_steps
            else "skipped"
            if key in state.skipped_steps
            else "pending"
        )
        steps.append({"key": key, "status": status})
    return {
        "current_step": state.current_step,
        "steps": steps,
        "answers": state.data,
        "completed_at": state.completed_at,
    }


PERMS: list[Any] = [
    IsAuthenticated,
    HasOrganisation,
    HasMethodPermission.for_({"GET": perms.SETTINGS_VIEW, "POST": perms.SETTINGS_MANAGE}),
]


class OnboardingStateView(APIView):
    permission_classes = PERMS

    @extend_schema(responses=OnboardingStateSerializer)
    def get(self, request: Request) -> Response:
        return Response(state_payload(onboarding.get_state()))


class OnboardingStepView(APIView):
    """Submit (or ``{"skip": true}``) one wizard step; ``complete`` finishes the wizard.

    Steps: business, locale, branding, service, tutors (teams/agencies), students,
    payments, invoicing.
    """

    permission_classes = PERMS

    @extend_schema(
        request={"application/json": OpenApiTypes.OBJECT},
        responses=OnboardingStateSerializer,
        examples=[
            OpenApiExample(
                "business",
                value={"business_type": "agency", "team_size": "6-20"},
                request_only=True,
            ),
            OpenApiExample(
                "service",
                value={
                    "subject": "Maths",
                    "level": "GCSE",
                    "duration_minutes": 60,
                    "price": {"amount": "40.00", "currency": "GBP"},
                },
                request_only=True,
            ),
            OpenApiExample("skip a step", value={"skip": True}, request_only=True),
        ],
    )
    def post(self, request: Request, step: str) -> Response:
        if step == "complete":
            return Response(state_payload(onboarding.complete()))
        body = request.data if isinstance(request.data, dict) else {}
        skip = bool(body.get("skip"))
        state = onboarding.submit_step(
            step, {k: v for k, v in body.items() if k != "skip"}, skip=skip
        )
        return Response(state_payload(state))
