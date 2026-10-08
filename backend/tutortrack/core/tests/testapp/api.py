from typing import Any

from django.db.models import QuerySet
from django.urls import include, path
from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from tutortrack.core.api.mixins import ConditionalUpdateMixin
from tutortrack.core.api.serializers import BaseModelSerializer
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import BusinessRuleViolation

from .models import Gadget, Widget


class GadgetSerializer(BaseModelSerializer):
    class Meta:
        model = Gadget
        fields = ["id", "name"]


class WidgetSerializer(BaseModelSerializer):
    class Meta:
        model = Widget
        fields = ["id", "name", "currency", "price", "hourly_rate", "gadget", "created_at"]
        expandable_fields = {"gadget": (GadgetSerializer, {})}


class WidgetViewSet(TenantScopedViewMixin, ConditionalUpdateMixin, viewsets.ModelViewSet):
    model = Widget
    serializer_class = WidgetSerializer

    def get_tenant_queryset(self) -> QuerySet[Widget]:
        return Widget.objects.all()


@api_view(["GET"])
@permission_classes([AllowAny])
def domain_error(request: Request) -> Response:
    raise BusinessRuleViolation("Lessons cannot overlap.", extra={"code": "overlap"})


class EchoSerializer(serializers.Serializer):
    value = serializers.IntegerField()


CALLS = {"count": 0}


@api_view(["POST"])
def echo(request: Request) -> Response:
    """Counts calls so tests can prove idempotent replays don't re-execute the view."""
    data = EchoSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    CALLS["count"] += 1
    status_code = int(request.query_params.get("status", 201))
    return Response(
        {"value": data.validated_data["value"], "call": CALLS["count"]}, status=status_code
    )


router = SimpleRouter(trailing_slash=False)
router.register("widgets", WidgetViewSet, basename="widgets")

urlpatterns: list[Any] = [
    path("api/v1/test/", include(router.urls)),
    path("api/v1/test/domain-error", domain_error),
    path("api/v1/test/echo", echo),
    path("", include("config.urls")),
]
