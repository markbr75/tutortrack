"""Developer platform API (E27).

Internal (first-party, session): API keys, OAuth apps, connected apps, sandboxes, overview,
marketplace, the OAuth consent endpoints. Public (also reachable with a token, see
``scopes.PUBLIC_VIEWS``): webhook endpoints, deliveries and the event catalogue. The OAuth
token/revoke endpoints authenticate the client, and the developer docs are anonymous.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.context import current_organisation_id
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, HasPermission

from .. import catalogue, connectors, docs, marketplace, ratelimit, selectors, services
from ..models import (
    ApiKey,
    OAuthApplication,
    OAuthGrant,
    Sandbox,
    WebhookDelivery,
    WebhookEndpoint,
)
from . import serializers as s

AUTH: list[Any] = [IsAuthenticated, HasOrganisation]


def _credential(request: Request) -> Any:
    return getattr(request._request, "api_credential", None)


# --- API keys -----------------------------------------------------------------------------------


@extend_schema(tags=["developer"])
class ApiKeyViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """API keys (secrets are shown once, on create and rotate)."""

    model = ApiKey
    serializer_class = s.ApiKeySerializer
    permission_classes = [*AUTH, HasPermission.for_("developer.apikey.manage")]

    def get_tenant_queryset(self) -> Any:
        return selectors.api_keys(self.request.user)

    @extend_schema(request=s.ApiKeyCreateSerializer, responses={201: s.ApiKeySecretSerializer})
    def create(self, request: Request) -> Response:
        payload = s.ApiKeyCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        key, secret = services.create_api_key(
            name=data["name"],
            scopes_=data["scopes"],
            user=request.user,
            branch=data.get("branch"),
            ip_allowlist=data.get("ip_allowlist") or [],
            expires_at=data.get("expires_at"),
            rate_limit_per_minute=data.get("rate_limit_per_minute"),
        )
        body = s.ApiKeySecretSerializer(key, context={"secret": secret}).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.ApiKeyUpdateSerializer, responses=s.ApiKeySerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.ApiKeyUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        key = services.update_api_key(self.get_object(), **payload.validated_data)
        return Response(s.ApiKeySerializer(key).data)

    @extend_schema(request=None, responses={201: s.ApiKeySecretSerializer})
    @action(detail=True, methods=["post"])
    def rotate(self, request: Request, pk: Any = None) -> Response:
        """A replacement key; the old one keeps working for the overlap period."""
        key, secret = services.rotate_api_key(self.get_object(), user=request.user)
        body = s.ApiKeySecretSerializer(key, context={"secret": secret}).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=s.ApiKeySerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request: Request, pk: Any = None) -> Response:
        key = services.revoke_api_key(self.get_object())
        return Response(s.ApiKeySerializer(key).data)


class ScopesView(APIView):
    """The scope catalogue and the permissions each scope covers."""

    permission_classes = AUTH

    @extend_schema(tags=["developer"], responses=s.ScopeSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.ScopeSerializer(s.scope_rows(), many=True).data)


class OverviewView(APIView):
    permission_classes = [*AUTH, HasPermission.for_("developer.webhook.view")]

    @extend_schema(tags=["developer"], responses=s.OverviewSerializer)
    def get(self, request: Request) -> Response:
        per_minute, burst = ratelimit.limits()
        body = {
            **selectors.usage_summary(request.user),
            "sandbox_of": selectors.sandbox_of(),
            "rate_limit_per_minute": per_minute,
            "burst_per_second": burst,
        }
        return Response(s.OverviewSerializer(body).data)


# --- OAuth applications and connected apps ------------------------------------------------------


@extend_schema(tags=["developer"])
class OAuthApplicationViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """OAuth2 apps this organisation registered (authorisation code + PKCE)."""

    model = OAuthApplication
    serializer_class = s.OAuthApplicationSerializer
    permission_classes = [*AUTH, HasPermission.for_("developer.app.manage")]

    def get_queryset(self) -> Any:
        if getattr(self, "swagger_fake_view", False):
            return OAuthApplication.objects.none()
        return selectors.oauth_applications(self.request.user)

    @extend_schema(
        request=s.OAuthApplicationWriteSerializer,
        responses={201: s.OAuthApplicationSecretSerializer},
    )
    def create(self, request: Request) -> Response:
        payload = s.OAuthApplicationWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        app, secret = services.register_application(user=request.user, **payload.validated_data)
        body = s.OAuthApplicationSecretSerializer(app, context={"client_secret": secret}).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=s.OAuthApplicationPatchSerializer, responses=s.OAuthApplicationSerializer
    )
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.OAuthApplicationPatchSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        app = services.update_application(self.get_object(), **payload.validated_data)
        return Response(s.OAuthApplicationSerializer(app).data)

    def destroy(self, request: Request, pk: Any = None) -> Response:
        services.delete_application(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=s.OAuthApplicationSecretSerializer)
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request: Request, pk: Any = None) -> Response:
        app = self.get_object()
        secret = services.rotate_client_secret(app)
        return Response(
            s.OAuthApplicationSecretSerializer(app, context={"client_secret": secret}).data
        )


@extend_schema(tags=["developer"])
class ConnectedAppViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Third-party apps people in this organisation have authorised."""

    model = OAuthGrant
    serializer_class = s.ConnectedAppSerializer
    permission_classes = [*AUTH, HasPermission.for_("developer.app.connect")]

    def get_tenant_queryset(self) -> Any:
        return selectors.connected_apps(self.request.user)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["post"])
    def revoke(self, request: Request, pk: Any = None) -> Response:
        services.revoke_grant(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


def _oauth_error(exc: services.OAuthError) -> Response:
    return Response(exc.as_dict(), status=exc.status)


class AuthorizeView(APIView):
    """The consent screen's data (GET) and the user's decision (POST)."""

    permission_classes = [*AUTH, HasPermission.for_("developer.app.connect")]

    @extend_schema(
        tags=["oauth"],
        parameters=[s.AuthorizeQuerySerializer],
        responses={200: s.ConsentSerializer, 400: OpenApiResponse(description="OAuth error")},
    )
    def get(self, request: Request) -> Response:
        query = s.AuthorizeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        q = query.validated_data
        try:
            app, scopes_ = services.validate_authorization(
                client_id=q["client_id"],
                redirect_uri=q["redirect_uri"],
                response_type=q["response_type"],
                scope=q["scope"],
                code_challenge=q["code_challenge"],
                code_challenge_method=q["code_challenge_method"],
            )
        except services.OAuthError as exc:
            return _oauth_error(exc)
        from tutortrack.developer.scopes import scope_label

        body = {
            "application": app,
            "scopes": [{"key": sc, "description": scope_label(sc)} for sc in scopes_],
            "redirect_uri": q["redirect_uri"],
            "state": q["state"],
            "organisation_name": request.organisation.name,  # type: ignore[attr-defined]
        }
        return Response(s.ConsentSerializer(body).data)

    @extend_schema(
        tags=["oauth"],
        request=s.AuthorizeDecisionSerializer,
        responses={200: s.OAuthRedirectSerializer, 400: OpenApiResponse(description="OAuth error")},
    )
    def post(self, request: Request) -> Response:
        payload = s.AuthorizeDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        q = payload.validated_data
        try:
            app, scopes_ = services.validate_authorization(
                client_id=q["client_id"],
                redirect_uri=q["redirect_uri"],
                response_type=q["response_type"],
                scope=q["scope"],
                code_challenge=q["code_challenge"],
                code_challenge_method=q["code_challenge_method"],
            )
        except services.OAuthError as exc:
            return _oauth_error(exc)
        if not q["approve"]:
            target = services.redirect_with(
                q["redirect_uri"], error="access_denied", state=q["state"]
            )
            return Response({"redirect_to": target})
        code = services.approve_authorization(
            app=app,
            user=request.user,
            scopes_=scopes_,
            redirect_uri=q["redirect_uri"],
            code_challenge=q["code_challenge"],
            code_challenge_method=q["code_challenge_method"],
        )
        return Response(
            {"redirect_to": services.redirect_with(q["redirect_uri"], code=code, state=q["state"])}
        )


@method_decorator(csrf_exempt, name="dispatch")
class TokenView(APIView):
    """OAuth2 token endpoint (RFC 6749): ``authorization_code`` (with PKCE) and
    ``refresh_token`` grants. Errors use the OAuth format, not problem details."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser, JSONParser]

    @extend_schema(
        tags=["oauth"],
        request=s.TokenRequestSerializer,
        responses={200: s.TokenResponseSerializer, 400: OpenApiResponse(description="OAuth error")},
    )
    def post(self, request: Request) -> Response:
        payload = s.TokenRequestSerializer(data=request.data)
        if not payload.is_valid():
            return Response({"error": "invalid_request"}, status=400)
        d = payload.validated_data
        try:
            if d["grant_type"] == "authorization_code":
                body = services.exchange_code(
                    client_id=d["client_id"],
                    client_secret=d["client_secret"],
                    code=d["code"],
                    redirect_uri=d["redirect_uri"],
                    code_verifier=d["code_verifier"],
                )
            else:
                body = services.refresh_tokens(
                    client_id=d["client_id"],
                    client_secret=d["client_secret"],
                    refresh_token=d["refresh_token"],
                )
        except services.OAuthError as exc:
            return _oauth_error(exc)
        return Response(body, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@method_decorator(csrf_exempt, name="dispatch")
class RevokeView(APIView):
    """OAuth2 token revocation (RFC 7009)."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]
    parser_classes = [FormParser, JSONParser]

    @extend_schema(tags=["oauth"], request=s.RevokeRequestSerializer, responses={200: None})
    def post(self, request: Request) -> Response:
        payload = s.RevokeRequestSerializer(data=request.data)
        if not payload.is_valid():
            return Response({"error": "invalid_request"}, status=400)
        d = payload.validated_data
        try:
            services.revoke_token(
                client_id=d["client_id"], client_secret=d["client_secret"], token=d["token"]
            )
        except services.OAuthError as exc:
            return _oauth_error(exc)
        return Response(status=200)


# --- webhooks (public) --------------------------------------------------------------------------


@extend_schema(tags=["webhooks"])
class WebhookEndpointViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Webhook endpoints: HTTPS URLs that receive signed event notifications. Also the
    REST-hook subscription API used by Zapier and Make."""

    model = WebhookEndpoint
    serializer_class = s.WebhookEndpointSerializer
    permission_classes = [
        *AUTH,
        HasMethodPermission.for_(
            {"GET": "developer.webhook.view", "*": "developer.webhook.manage"}
        ),
    ]

    def get_tenant_queryset(self) -> Any:
        return selectors.webhook_endpoints(self.request.user)

    def _source(self) -> str:
        credential = _credential(self.request)
        if credential is None:
            return WebhookEndpoint.Source.MANUAL
        if credential.application_id:
            app = OAuthApplication.objects.filter(pk=credential.application_id).first()
            if app is not None and app.partner_key in ("zapier", "make"):
                return app.partner_key
        return WebhookEndpoint.Source.API

    @extend_schema(
        request=s.WebhookEndpointCreateSerializer,
        responses={201: s.WebhookEndpointSecretSerializer},
    )
    def create(self, request: Request) -> Response:
        payload = s.WebhookEndpointCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        endpoint, secret = services.create_endpoint(
            url=d["url"],
            events_=d["events"],
            description=d.get("description", ""),
            branch=d.get("branch"),
            source=self._source(),
        )
        body = s.WebhookEndpointSecretSerializer(endpoint, context={"secret": secret}).data
        return Response(body, status=status.HTTP_201_CREATED)

    @extend_schema(request=s.WebhookEndpointPatchSerializer, responses=s.WebhookEndpointSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = s.WebhookEndpointPatchSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        endpoint = services.update_endpoint(self.get_object(), **payload.validated_data)
        return Response(s.WebhookEndpointSerializer(endpoint).data)

    def destroy(self, request: Request, pk: Any = None) -> Response:
        services.delete_endpoint(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=s.SecretSerializer)
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request: Request, pk: Any = None) -> Response:
        """New signing secret; the old one also signs for 24 hours."""
        return Response({"secret": services.rotate_endpoint_secret(self.get_object())})

    @extend_schema(request=None, responses=s.SecretSerializer)
    @action(detail=True, methods=["post"], url_path="reveal-secret")
    def reveal_secret(self, request: Request, pk: Any = None) -> Response:
        """Show the signing secret (the read is audited)."""
        return Response({"secret": services.reveal_secret(self.get_object())})

    @extend_schema(request=None, responses={202: s.WebhookDeliverySerializer})
    @action(detail=True, methods=["post"])
    def test(self, request: Request, pk: Any = None) -> Response:
        """Send a ``webhook.test`` event now."""
        delivery = services.send_test_event(self.get_object())
        return Response(s.WebhookDeliverySerializer(delivery).data, status=status.HTTP_202_ACCEPTED)


@extend_schema(tags=["webhooks"])
class WebhookDeliveryViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """The delivery log (30 days): each delivery with its attempts."""

    model = WebhookDelivery
    permission_classes = [
        *AUTH,
        HasMethodPermission.for_(
            {"GET": "developer.webhook.view", "*": "developer.webhook.manage"}
        ),
    ]

    def get_serializer_class(self) -> Any:
        if self.action == "retrieve":
            return s.WebhookDeliveryDetailSerializer
        return s.WebhookDeliverySerializer

    def get_tenant_queryset(self) -> Any:
        qs = selectors.webhook_deliveries(
            self.request.user,
            endpoint=self.request.query_params.get("endpoint") or None,
            status=self.request.query_params.get("status", ""),
        )
        if self.action == "retrieve":
            qs = qs.prefetch_related("attempts")
        return qs

    @extend_schema(
        parameters=[
            OpenApiParameter("endpoint", str, required=False),
            OpenApiParameter(
                "status", str, required=False, enum=[c for c, _l in WebhookDelivery.Status.choices]
            ),
        ]
    )
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses={202: s.WebhookDeliverySerializer})
    @action(detail=True, methods=["post"])
    def redeliver(self, request: Request, pk: Any = None) -> Response:
        delivery = services.redeliver(self.get_object())
        return Response(s.WebhookDeliverySerializer(delivery).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(request=None, responses={202: None})
    @action(detail=True, methods=["post"], url_path="retry-now")
    def retry_now(self, request: Request, pk: Any = None) -> Response:
        services.retry_now(self.get_object())
        return Response(status=status.HTTP_202_ACCEPTED)


class EventTypesView(APIView):
    """Event types an endpoint can subscribe to (also ``<aggregate>.*``)."""

    permission_classes = [*AUTH, HasPermission.for_("developer.webhook.view")]

    @extend_schema(tags=["webhooks"], responses=s.EventTypeSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = [e.__dict__ for e in catalogue.event_types()]
        return Response(s.EventTypeSerializer(rows, many=True).data)


class EventSampleView(APIView):
    """An example payload: the latest real one of that type, else a synthetic one (Zapier
    and Make use it to show sample data)."""

    permission_classes = [*AUTH, HasPermission.for_("developer.webhook.view")]

    @extend_schema(tags=["webhooks"], responses=s.EventSampleSerializer)
    def get(self, request: Request, event_type: str) -> Response:
        if event_type not in catalogue.public_event_keys():
            raise NotFound()
        real = selectors.latest_payload(event_type)
        body = real or catalogue.sample_payload(
            event_type, current_organisation_id(), settings.DEVELOPER_API["WEBHOOK_API_VERSION"]
        )
        return Response({"event_type": event_type, "synthetic": real is None, "body": body})


# --- sandboxes and marketplace ------------------------------------------------------------------


@extend_schema(tags=["developer"])
class SandboxViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Sandbox organisations: a copy of the settings with sample data, for testing."""

    model = Sandbox
    serializer_class = s.SandboxSerializer
    permission_classes = [*AUTH, HasPermission.for_("developer.sandbox.manage")]

    def get_tenant_queryset(self) -> Any:
        return selectors.sandboxes(self.request.user)

    @extend_schema(request=None, responses={201: s.SandboxSerializer})
    def create(self, request: Request) -> Response:
        sandbox = services.create_sandbox(user=request.user)
        return Response(s.SandboxSerializer(sandbox).data, status=status.HTTP_201_CREATED)


class MarketplaceView(APIView):
    """Native integrations with their connection status, plus partner apps."""

    permission_classes = AUTH

    @extend_schema(tags=["developer"], responses=s.MarketplaceEntrySerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.MarketplaceEntrySerializer(marketplace.entries(), many=True).data)


# --- developer docs (anonymous) -----------------------------------------------------------------


class _Anonymous(APIView):
    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]


class PublicSchemaView(_Anonymous):
    """The OpenAPI document of the public API only (rendered by the docs portal)."""

    @extend_schema(
        tags=["developer-docs"],
        responses=inline_serializer("PublicOpenApi", {"openapi": serializers.CharField()}),
    )
    def get(self, request: Request) -> Response:
        return Response(docs.public_schema())


class PostmanView(_Anonymous):
    """A Postman v2.1 collection of the public API."""

    @extend_schema(
        tags=["developer-docs"],
        responses=inline_serializer("PostmanCollection", {"info": serializers.DictField()}),
    )
    def get(self, request: Request) -> Response:
        return Response(
            docs.postman_collection(),
            headers={"Content-Disposition": 'attachment; filename="tutortrack.postman.json"'},
        )


class ChangelogView(_Anonymous):
    @extend_schema(tags=["developer-docs"], responses=s.ChangelogEntrySerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(s.ChangelogEntrySerializer(docs.changelog(), many=True).data)


class ConnectorView(_Anonymous):
    """The Zapier or Make app definition (triggers, actions, searches, OAuth settings)."""

    @extend_schema(
        tags=["developer-docs"],
        responses=inline_serializer("ConnectorManifest", {"platform": serializers.CharField()}),
    )
    def get(self, request: Request, platform: str) -> Response:
        try:
            return Response(connectors.manifest(platform))
        except KeyError as exc:
            raise NotFound() from exc
