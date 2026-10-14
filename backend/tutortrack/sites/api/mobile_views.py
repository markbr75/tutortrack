"""``GET /api/v1/public/mobile-app`` (E16-T11): the native app shell configuration for the
organisation of the request's host (public brand data, like the PWA manifest). The manual
mobile build workflow fetches it to configure a white-label build."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from .. import mobile
from .views import PublicView, _org


class MobileAppConfigSerializer(serializers.Serializer):
    white_label = serializers.BooleanField()
    appId = serializers.CharField()
    appName = serializers.CharField()
    serverUrl = serializers.CharField(allow_blank=True)
    allowNavigation = serializers.ListField(child=serializers.CharField())
    primaryColour = serializers.CharField()
    onPrimary = serializers.CharField()
    backgroundColour = serializers.CharField()
    iconUrl = serializers.CharField(allow_blank=True)
    organisation = serializers.CharField(allow_null=True)


@extend_schema(tags=["public"])
class PublicMobileAppView(PublicView):
    """White-label app configuration (generic when the plan has no white-label apps)."""

    @extend_schema(responses=MobileAppConfigSerializer)
    def get(self, request: Request) -> Response:
        return Response(mobile.app_config(_org(request)))
