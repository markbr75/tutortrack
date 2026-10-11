"""Integration framework API (E22-T01): providers, connections, OAuth and credentials."""

from __future__ import annotations

import urllib.parse
from typing import Any

from django.http import HttpResponseRedirect
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import PermissionDenied
from tutortrack.core.permissions import HasOrganisation, has_perm

from .. import oauth, providers, selectors, services
from ..models import IntegrationConnection
from . import serializers as s

AUTH = [IsAuthenticated, HasOrganisation]


def _may_connect(user: Any, level: str, provider: str = "") -> None:
    if level == "organisation":
        if not selectors.may_manage_provider(user, provider):
            raise PermissionDenied("You can't connect integrations.")
        return
    if not (has_perm(user, "integrations.personal") or has_perm(user, "integrations.manage")):
        raise PermissionDenied("You can't connect integrations.")


class ProvidersView(APIView):
    permission_classes = AUTH

    @extend_schema(responses=s.ProviderSerializer(many=True))
    def get(self, request: Request) -> Response:
        """Providers that can be connected, what they do and how they connect."""
        rows = [
            {
                "key": spec.key,
                "name": spec.label,
                "capabilities": sorted(spec.capabilities),
                "auth": spec.auth,
                "levels": list(spec.levels),
                "credential_fields": list(spec.credential_fields),
                "simulated": providers.is_fake(spec.key),
            }
            for spec in providers.all_specs()
        ]
        return Response(s.ProviderSerializer(rows, many=True).data)


class IntegrationConnectionViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Connected accounts. Admins (``integrations.view``) see every connection with its
    health and last error; everyone else sees their own. ``?mine=1`` limits to your own,
    ``?capability=calendar|video`` filters."""

    model = IntegrationConnection
    serializer_class = s.IntegrationConnectionSerializer
    permission_classes = AUTH

    def get_tenant_queryset(self) -> Any:
        qs = selectors.visible_connections(self.request.user)
        params = self.request.query_params
        if params.get("mine"):
            qs = qs.filter(user=self.request.user)
        capability = params.get("capability")
        if capability:
            keys = [p.key for p in providers.all_specs() if capability in p.capabilities]
            qs = qs.filter(provider__in=keys)
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("mine", bool, required=False),
            OpenApiParameter(
                "capability", str, required=False, enum=["calendar", "video", "accounting"]
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(
        request=s.CredentialConnectSerializer,
        responses={201: s.IntegrationConnectionSerializer},
        examples=[
            OpenApiExample(
                "iCloud",
                value={
                    "provider": "caldav",
                    "username": "sam@icloud.com",
                    "password": "abcd-efgh-ijkl-mnop",
                },
                request_only=True,
            )
        ],
    )
    def create(self, request: Request) -> Response:
        """Connect with credentials: CalDAV (iCloud app-specific password) or an API key
        (Lessonspace). Verified at the provider, then stored encrypted."""
        payload = s.CredentialConnectSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        _may_connect(request.user, data["level"], data["provider"])
        connection = services.connect_with_credentials(request.user, **data)
        return Response(
            s.IntegrationConnectionSerializer(connection).data, status=status.HTTP_201_CREATED
        )

    def _managed(self) -> IntegrationConnection:
        connection: IntegrationConnection = self.get_object()
        if not selectors.can_manage(self.request.user, connection):
            raise PermissionDenied("You can't change this connection.")
        return connection

    @extend_schema(request=None, responses=s.IntegrationConnectionSerializer)
    @action(detail=True, methods=["post"])
    def disconnect(self, request: Request, pk: str) -> Response:
        """Revoke our access at the provider (best effort) and forget the tokens. Calendar
        sync stops; events already written stay in the calendar."""
        connection = services.disconnect(self._managed())
        return Response(s.IntegrationConnectionSerializer(connection).data)

    @extend_schema(request=None, responses=s.IntegrationConnectionSerializer)
    @action(detail=True, methods=["post"])
    def check(self, request: Request, pk: str) -> Response:
        """Health check: refresh the token if needed and make a light provider call."""
        connection = services.check(self._managed())
        return Response(s.IntegrationConnectionSerializer(connection).data)


class OAuthStartView(APIView):
    permission_classes = AUTH

    @extend_schema(
        request=s.OAuthStartSerializer,
        responses=s.OAuthStartResultSerializer,
        examples=[
            OpenApiExample(
                "Google Calendar",
                value={"provider": "google", "level": "user", "next": "/settings/integrations"},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        """Begin connecting an OAuth provider: open ``authorize_url`` in the browser."""
        payload = s.OAuthStartSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        _may_connect(request.user, data["level"], data["provider"])
        url = services.start_oauth(
            request.user, provider=data["provider"], level=data["level"], next_path=data["next"]
        )
        return Response({"authorize_url": url})


class OAuthCallbackView(APIView):
    """The provider redirects here (root app host); we forward the browser to the
    organisation's app, which completes the connection while signed in."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []

    @extend_schema(
        parameters=[
            OpenApiParameter("code", str),
            OpenApiParameter("state", str),
            OpenApiParameter("error", str, required=False),
            OpenApiParameter("realmId", str, required=False),
        ],
        responses={302: None},
    )
    def get(self, request: Request) -> HttpResponseRedirect:
        from django.conf import settings

        from tutortrack.tenancy.models import Organisation

        token = request.query_params.get("state", "")
        try:
            state = oauth.read_state(token)
        except oauth.OAuthStateError:
            return HttpResponseRedirect(f"{settings.APP_URL}/?integration_error=state")
        org = Organisation.objects.filter(pk=state.organisation_id).first()
        base = org.base_url if org is not None else settings.APP_URL
        params = (
            {"integration_error": request.query_params.get("error", "denied")[:50]}
            if request.query_params.get("error") or not request.query_params.get("code")
            else {"code": request.query_params["code"], "state": token}
        )
        # Providers that name the connected account only on the redirect (QuickBooks).
        if "code" in params and request.query_params.get("realmId"):
            params["account_id"] = request.query_params["realmId"][:100]
        separator = "&" if "?" in state.next_path else "?"
        return HttpResponseRedirect(
            f"{base}{state.next_path}{separator}{urllib.parse.urlencode(params)}"
        )


class OAuthCompleteView(APIView):
    permission_classes = AUTH

    @extend_schema(
        request=s.OAuthCompleteSerializer,
        responses={201: s.IntegrationConnectionSerializer},
    )
    def post(self, request: Request) -> Response:
        """Finish connecting: exchange the code (PKCE). Only the person who started the
        connection, in the same organisation, can finish it."""
        payload = s.OAuthCompleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        connection = services.complete_oauth(request.user, **payload.validated_data)
        return Response(
            s.IntegrationConnectionSerializer(connection).data, status=status.HTTP_201_CREATED
        )
