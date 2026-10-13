"""Identity Phase 2 API (E03-T08 passkeys, T11 custom roles, T12 organisation SSO)."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db.models import QuerySet
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_field
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core import audit
from tutortrack.core.api.serializers import BaseModelSerializer
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation

from .. import auth, org_sso, passkeys, services
from ..models import Membership, OrganisationSSO, Role, User, WebAuthnCredential

# --- serializers ---------------------------------------------------------------------------------


class CustomRoleSerializer(BaseModelSerializer):
    grants = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()

    class Meta:
        model = Role
        fields = ["id", "name", "description", "base_role", "grants", "members", "archived_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_grants(self, obj: Role) -> dict[str, str]:
        return services.role_matrix(obj)

    @extend_schema_field(serializers.IntegerField())
    def get_members(self, obj: Role) -> int:
        return obj.membership_links.count()


class CustomRoleInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    clone_from = serializers.CharField(
        max_length=64, required=False, allow_blank=True, help_text="A staff role key or role id."
    )
    grants = serializers.DictField(
        child=serializers.ChoiceField(choices=["all", "branch", "own", "none"], allow_null=True),
        required=False,
        help_text="{codename: scope}; none or null removes it.",
    )


class CustomRoleUpdateSerializer(CustomRoleInputSerializer):
    name = serializers.CharField(max_length=100, required=False)


class CredentialSerializer(BaseModelSerializer):
    class Meta:
        model = WebAuthnCredential
        fields = ["id", "name", "backed_up", "transports", "created_at", "last_used_at"]
        read_only_fields = fields


class PublicKeyOptionsSerializer(serializers.Serializer):
    """``PublicKeyCredential{Creation,Request}Options`` as JSON (base64url binary)."""

    challenge = serializers.CharField()
    rpId = serializers.CharField(required=False)
    rp = serializers.DictField(required=False)
    user = serializers.DictField(required=False)
    timeout = serializers.IntegerField(required=False)
    pubKeyCredParams = serializers.ListField(child=serializers.DictField(), required=False)
    allowCredentials = serializers.ListField(child=serializers.DictField(), required=False)
    excludeCredentials = serializers.ListField(child=serializers.DictField(), required=False)
    userVerification = serializers.CharField(required=False)


class PasskeyRegisterSerializer(serializers.Serializer):
    credential = serializers.DictField()
    name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class PasskeyRegisteredSerializer(serializers.Serializer):
    credential = CredentialSerializer()
    recovery_codes = serializers.ListField(child=serializers.CharField())


class PasskeyAssertionSerializer(serializers.Serializer):
    credential = serializers.DictField()
    remember = serializers.BooleanField(required=False, default=False)


class OrganisationSSOSerializer(BaseModelSerializer):
    client_secret = serializers.CharField(
        write_only=True, required=False, allow_blank=True, max_length=500
    )
    has_client_secret = serializers.SerializerMethodField()
    sp_entity_id = serializers.SerializerMethodField()
    acs_url = serializers.SerializerMethodField()
    callback_url = serializers.SerializerMethodField()
    complete = serializers.SerializerMethodField()
    email_domains = serializers.ListField(
        child=serializers.CharField(max_length=253), required=False, max_length=20
    )
    default_role = serializers.ChoiceField(
        choices=[r for r in Membership.Role.choices if r[0] != "owner"], required=False
    )

    class Meta:
        model = OrganisationSSO
        fields = [
            "protocol", "enabled", "name", "email_domains", "enforce", "auto_provision",
            "default_role", "issuer", "client_id", "client_secret", "has_client_secret",
            "idp_entity_id", "idp_sso_url", "idp_certificate", "sp_entity_id", "acs_url",
            "callback_url", "complete",
        ]  # fmt: skip

    def get_has_client_secret(self, obj: OrganisationSSO) -> bool:
        return bool(obj.client_secret)

    def _req(self) -> Any:
        return self.context["request"]._request

    def get_sp_entity_id(self, obj: OrganisationSSO) -> str:
        return org_sso.sp_entity_id(self._req())

    def get_acs_url(self, obj: OrganisationSSO) -> str:
        return org_sso.acs_url(self._req())

    def get_callback_url(self, obj: OrganisationSSO) -> str:
        return org_sso.callback_url(self._req())

    def get_complete(self, obj: OrganisationSSO) -> bool:
        return org_sso.is_complete(obj)


class OrgSSOInfoSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    name = serializers.CharField(allow_blank=True)
    start_url = serializers.CharField(allow_blank=True)
    enforced_domains = serializers.ListField(child=serializers.CharField())


# --- custom roles (T11) --------------------------------------------------------------------------


ROLE_PERMS = HasMethodPermission.for_({"GET": "team.view", "*": "team.roles.manage"})


class CustomRoleViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Custom roles: clone a staff role and edit its permission matrix (FR-03-5)."""

    model = Role
    serializer_class = CustomRoleSerializer
    permission_classes = [IsAuthenticated, HasOrganisation, ROLE_PERMS]
    pagination_class = None

    def get_tenant_queryset(self) -> QuerySet[Role]:
        qs = Role.objects.all()
        if self.request.query_params.get("include_archived") not in {"1", "true"}:
            qs = qs.filter(archived_at__isnull=True)
        return qs

    @extend_schema(request=CustomRoleInputSerializer, responses={201: CustomRoleSerializer})
    def create(self, request: Request) -> Response:
        payload = CustomRoleInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        role = services.create_custom_role(**payload.validated_data)
        return Response(CustomRoleSerializer(role).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=CustomRoleUpdateSerializer, responses=CustomRoleSerializer)
    def partial_update(self, request: Request, pk: Any = None) -> Response:
        payload = CustomRoleUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        data.pop("clone_from", None)
        role = services.update_custom_role(self.get_object(), **data)
        return Response(CustomRoleSerializer(role).data)

    @extend_schema(request=None, responses=CustomRoleSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request: Request, pk: Any = None) -> Response:
        return Response(CustomRoleSerializer(services.archive_custom_role(self.get_object())).data)


# --- passkeys (T08) ------------------------------------------------------------------------------


def _user(request: Request) -> User:
    user = request.user
    if not isinstance(user, User):
        raise NotFound()
    return user


class PasskeyListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=CredentialSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(
            CredentialSerializer(_user(request).webauthn_credentials.all(), many=True).data
        )


class PasskeyDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, pk: Any) -> Response:
        credential = get_object_or_404(WebAuthnCredential, pk=pk, user=_user(request))
        passkeys.remove(credential)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasskeyRegisterOptionsView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=PublicKeyOptionsSerializer)
    def post(self, request: Request) -> Response:
        return Response(passkeys.registration_options(request._request, _user(request)))


class PasskeyRegisterView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasskeyRegisterSerializer, responses={201: PasskeyRegisteredSerializer})
    def post(self, request: Request) -> Response:
        payload = PasskeyRegisterSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        credential, codes = passkeys.register(
            request._request,
            _user(request),
            payload.validated_data["credential"],
            name=payload.validated_data["name"],
        )
        return Response(
            {"credential": CredentialSerializer(credential).data, "recovery_codes": codes},
            status=status.HTTP_201_CREATED,
        )


class Throttled(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa"
    permission_classes = [AllowAny]


class PasskeyAuthOptionsView(Throttled):
    """Options for a passkey: as the second factor while sign-in waits for it, otherwise
    for passkey-only sign-in (any discoverable credential)."""

    @extend_schema(request=None, responses=PublicKeyOptionsSerializer)
    def post(self, request: Request) -> Response:
        user = None
        try:
            user, _pending = auth.pending_mfa_user(request._request)
        except auth.MFANotPending:
            user = None
        return Response(passkeys.authentication_options(request._request, user))


class PasskeyVerifyView(Throttled):
    """Finish sign-in with a passkey (second factor or passkey-only)."""

    @extend_schema(request=PasskeyAssertionSerializer, responses={200: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        from .serializers import UserSerializer

        payload = PasskeyAssertionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        try:
            auth.pending_mfa_user(request._request)
            pending = True
        except auth.MFANotPending:
            pending = False
        if pending:
            user = passkeys.verify_second_factor(request._request, data["credential"])
        else:
            user = passkeys.login_with_passkey(
                request._request, data["credential"], remember=data["remember"]
            )
        return Response({"mfa_required": False, "user": UserSerializer(user).data})


# --- organisation SSO (T12) ----------------------------------------------------------------------


class OrganisationSSOView(APIView):
    """The organisation's identity provider settings (Enterprise)."""

    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"GET": "security.sso.manage", "PUT": "security.sso.manage"}),
    ]

    def _get(self) -> OrganisationSSO:
        found, _created = OrganisationSSO.objects.get_or_create()
        return found

    @extend_schema(responses=OrganisationSSOSerializer)
    def get(self, request: Request) -> Response:
        return Response(OrganisationSSOSerializer(self._get(), context={"request": request}).data)

    @extend_schema(request=OrganisationSSOSerializer, responses=OrganisationSSOSerializer)
    def put(self, request: Request) -> Response:
        from tutortrack.core import entitlements
        from tutortrack.core.exceptions import BusinessRuleViolation

        cfg = self._get()
        payload = OrganisationSSOSerializer(
            cfg, data=request.data, partial=True, context={"request": request}
        )
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        if data.get("client_secret") == "":
            data.pop("client_secret")  # blank keeps the stored secret
        if "email_domains" in data:
            data["email_domains"] = sorted(
                {d.strip().lower().lstrip("@") for d in data["email_domains"] if d.strip()}
            )
        if data.get("enabled") and not entitlements.has("sso_saml"):
            raise BusinessRuleViolation("Single sign-on is part of the Enterprise plan.")
        with audit.track(cfg):
            for k, v in data.items():
                setattr(cfg, k, v)
            if cfg.enabled and not org_sso.is_complete(cfg):
                raise BusinessRuleViolation(
                    "Fill in the identity provider details and at least one email domain."
                )
            cfg.save()
        return Response(OrganisationSSOSerializer(cfg, context={"request": request}).data)


class OrgSSOInfoView(APIView):
    """Whether this organisation offers its own sign-in (for the login page)."""

    permission_classes = [AllowAny]

    @extend_schema(responses=OrgSSOInfoSerializer)
    def get(self, request: Request) -> Response:
        cfg = org_sso.config() if getattr(request, "organisation", None) else None
        return Response(
            {
                "enabled": cfg is not None,
                "name": cfg.name if cfg else "",
                "start_url": "/api/v1/auth/org-sso/start" if cfg else "",
                "enforced_domains": list(cfg.email_domains) if cfg and cfg.enforce else [],
            }
        )


def _fail(code: str) -> HttpResponseRedirect:
    response = HttpResponseRedirect(f"/login?error=sso_{code}")
    response.delete_cookie(org_sso.STATE_COOKIE, path="/api/v1/auth/org-sso/")
    return response


def _finish(request: Request, user: User, state: dict[str, Any]) -> HttpResponseRedirect:
    result = auth._begin_or_complete(request._request, user, method="sso_org", remember=False)
    target = "/login?mfa=1" if result.mfa_required else state["x"]
    response = HttpResponseRedirect(target)
    response.delete_cookie(org_sso.STATE_COOKIE, path="/api/v1/auth/org-sso/")
    return response


class OrgSSOStartView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(parameters=[OpenApiParameter("next", str)], responses={302: None})
    def get(self, request: Request) -> HttpResponseRedirect:
        cfg = org_sso.config() if getattr(request, "organisation", None) else None
        if cfg is None:
            raise NotFound()
        try:
            url, cookie = org_sso.begin(
                request._request, cfg, next_path=request.query_params.get("next", "/")
            )
        except org_sso.SSOError as exc:
            return _fail(exc.code)
        response = HttpResponseRedirect(url)
        saml = cfg.protocol == OrganisationSSO.Protocol.SAML
        response.set_cookie(
            org_sso.STATE_COOKIE,
            cookie,
            max_age=org_sso.STATE_MAX_AGE,
            httponly=True,
            # The SAML response is a cross-site POST: Lax cookies aren't sent with it.
            secure=request.is_secure() or (saml and not settings.DEBUG),
            samesite="None" if saml and request.is_secure() else "Lax",
            path="/api/v1/auth/org-sso/",
        )
        return response


class OrgSSOCallbackView(APIView):
    """OIDC redirect back from the organisation's identity provider."""

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("code", str), OpenApiParameter("state", str)],
        responses={302: None},
    )
    def get(self, request: Request) -> HttpResponseRedirect:
        cfg = org_sso.config() if getattr(request, "organisation", None) else None
        if cfg is None or cfg.protocol != OrganisationSSO.Protocol.OIDC:
            raise NotFound()
        try:
            if request.query_params.get("error"):
                raise org_sso.SSOError("denied")
            state = org_sso.read_state(
                request.COOKIES.get(org_sso.STATE_COOKIE, ""),
                request.query_params.get("state", ""),
            )
            claims = org_sso.finish_oidc(
                request._request, cfg, request.query_params.get("code", ""), state
            )
            user = org_sso.match_user(cfg, claims)
        except org_sso.SSOError as exc:
            return _fail(exc.code)
        return _finish(request, user, state)


class SAMLResponseSerializer(serializers.Serializer):
    SAMLResponse = serializers.CharField()
    RelayState = serializers.CharField(required=False, allow_blank=True)


@method_decorator(csrf_exempt, name="dispatch")
class OrgSSOAcsView(APIView):
    """SAML assertion consumer service (HTTP-POST binding)."""

    permission_classes = [AllowAny]
    authentication_classes: list[Any] = []
    parser_classes = [FormParser, MultiPartParser]

    @extend_schema(request=SAMLResponseSerializer, responses={302: None})
    def post(self, request: Request) -> HttpResponseRedirect:
        cfg = org_sso.config() if getattr(request, "organisation", None) else None
        if cfg is None or cfg.protocol != OrganisationSSO.Protocol.SAML:
            raise NotFound()
        try:
            state = org_sso.read_state(
                request.COOKIES.get(org_sso.STATE_COOKIE, ""),
                str(request.POST.get("RelayState", "")),
            )
            claims = org_sso.finish_saml(
                request._request, cfg, str(request.POST.get("SAMLResponse", "")), state
            )
            user = org_sso.match_user(cfg, claims)
        except org_sso.SSOError as exc:
            return _fail(exc.code)
        return _finish(request, user, state)


class OrgSSOMetadataView(APIView):
    """SAML service provider metadata to give to the IdP administrator."""

    permission_classes = [AllowAny]

    @extend_schema(responses={(200, "application/samlmetadata+xml"): OpenApiTypes.STR})
    def get(self, request: Request) -> HttpResponse:
        if getattr(request, "organisation", None) is None:
            raise NotFound()
        return HttpResponse(
            org_sso.metadata(request._request), content_type="application/samlmetadata+xml"
        )
