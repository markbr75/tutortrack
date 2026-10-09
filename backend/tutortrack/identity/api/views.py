"""Identity API (E03): authentication, account, team and access control."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django_filters import rest_framework as filters
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    extend_schema,
    inline_serializer,
)
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from tutortrack.core import flags
from tutortrack.core.api.viewsets import TenantScopedViewMixin
from tutortrack.core.exceptions import BusinessRuleViolation, PermissionDenied
from tutortrack.core.permission_registry import all_permissions
from tutortrack.core.permissions import HasMethodPermission, HasOrganisation, scope_queryset

from .. import auth, impersonation, rbac, services, sso
from ..models import Invitation, Membership, User, UserSession
from ..roles import ROLES
from ..tokens import InvalidToken, handoff_token
from .serializers import (
    AcceptInvitationSerializer,
    BulkInviteResultSerializer,
    BulkInviteSerializer,
    CodeSerializer,
    EmailSerializer,
    ImpersonateSerializer,
    InvitationLookupSerializer,
    InvitationSerializer,
    LoginResultSerializer,
    LoginSerializer,
    LoginTokenSerializer,
    MembershipSerializer,
    MembershipUpdateSerializer,
    MeSerializer,
    PasswordChangeSerializer,
    PasswordConfirmSerializer,
    PasswordResetConfirmSerializer,
    PermissionSerializer,
    RecoveryCodesSerializer,
    RoleSerializer,
    SessionSerializer,
    SSOProviderSerializer,
    TOTPConfirmSerializer,
    TOTPSetupSerializer,
    UserSerializer,
)


class PasswordInvalid(BusinessRuleViolation):
    problem_type = "password-invalid"
    title = "Choose a stronger password"


def _user(request: Request) -> User:
    """The signed-in user (views using this require IsAuthenticated)."""
    user = request.user
    if not isinstance(user, User):
        raise PermissionDenied()
    return user


def _validated(serializer_class: type[serializers.Serializer], request: Request) -> Any:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _password_errors(exc: DjangoValidationError, field: str = "new_password") -> PasswordInvalid:
    return PasswordInvalid(exc.messages[0], extra={"errors": {field: exc.messages}})


def _login_result(request: Request, result: auth.LoginResult) -> Response:
    user = None if result.mfa_required else UserSerializer(result.user).data
    return Response({"mfa_required": result.mfa_required, "user": user})


class Throttled(APIView):
    throttle_classes = [ScopedRateThrottle]


# --- authentication -------------------------------------------------------------------------------


class LoginView(Throttled):
    """Email + password. When the user has 2FA, ``mfa_required`` is true and the session
    waits for ``POST /auth/mfa/verify``."""

    permission_classes = [AllowAny]
    throttle_scope = "login"

    @extend_schema(
        request=LoginSerializer,
        responses=LoginResultSerializer,
        examples=[
            OpenApiExample(
                "Sign in",
                value={"email": "sam@example.com", "password": "secret", "remember": False},
                request_only=True,
            )
        ],
    )
    def post(self, request: Request) -> Response:
        data = _validated(LoginSerializer, request)
        result = auth.login_with_password(
            request._request, data["email"], data["password"], remember=data["remember"]
        )
        return _login_result(request, result)


class MFAVerifyView(Throttled):
    permission_classes = [AllowAny]
    throttle_scope = "mfa"

    @extend_schema(request=CodeSerializer, responses=UserSerializer)
    def post(self, request: Request) -> Response:
        user = auth.verify_mfa(request._request, _validated(CodeSerializer, request)["code"])
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        impersonation.stop(request._request)
        auth.sign_out(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MagicLinkView(Throttled):
    """Email a single-use sign-in link (15 minutes). Always 202."""

    permission_classes = [AllowAny]
    throttle_scope = "magic_link"

    @extend_schema(request=EmailSerializer, responses={202: None})
    def post(self, request: Request) -> Response:
        data = _validated(EmailSerializer, request)
        auth.request_magic_link(request._request, data["email"], next_path=data["next"])
        return Response(status=status.HTTP_202_ACCEPTED)


class MagicLinkVerifyView(Throttled):
    permission_classes = [AllowAny]
    throttle_scope = "login"

    @extend_schema(request=LoginTokenSerializer, responses=LoginResultSerializer)
    def post(self, request: Request) -> Response:
        data = _validated(LoginTokenSerializer, request)
        result = auth.login_with_magic_link(
            request._request, data["token"], remember=data["remember"]
        )
        return _login_result(request, result)


class PasswordResetView(Throttled):
    """Email a reset link (1 hour, single use). Always 202."""

    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(request=EmailSerializer, responses={202: None})
    def post(self, request: Request) -> Response:
        auth.request_password_reset(request._request, _validated(EmailSerializer, request)["email"])
        return Response(status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(Throttled):
    permission_classes = [AllowAny]
    throttle_scope = "password_reset"

    @extend_schema(request=PasswordResetConfirmSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        data = _validated(PasswordResetConfirmSerializer, request)
        try:
            auth.reset_password(data["uid"], data["token"], data["new_password"])
        except DjangoValidationError as exc:
            raise _password_errors(exc) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class SSOProvidersView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=SSOProviderSerializer(many=True))
    def get(self, request: Request) -> Response:
        rows = [
            {"key": p.key, "start_url": f"{settings.APP_URL}/api/v1/auth/sso/{p.key}/start"}
            for p in sso.providers().values()
            if p.enabled
        ]
        return Response(rows)


def _sso_redirect_failure(code: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(f"{settings.APP_URL}/login?error=sso_{code}")


class SSOStartView(APIView):
    """Browser navigation: redirects to Google/Microsoft (open on the root app host)."""

    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("org", str, description="Organisation id to continue to."),
            OpenApiParameter("next", str, description="Path to open after signing in."),
            OpenApiParameter("intent", str, enum=["login", "signup"]),
        ],
        responses={302: None},
    )
    def get(self, request: Request, provider: str) -> HttpResponseRedirect:
        config = sso.get_provider(provider)
        if config is None:
            raise NotFound()
        url, cookie = sso.begin(
            config,
            organisation_id=request.query_params.get("org", ""),
            next_path=request.query_params.get("next", "/"),
            intent=request.query_params.get("intent", "login"),
        )
        response = HttpResponseRedirect(url)
        response.set_cookie(
            sso.STATE_COOKIE,
            cookie,
            max_age=sso.STATE_MAX_AGE,
            httponly=True,
            secure=request.is_secure(),
            samesite="Lax",
            path="/api/v1/auth/sso/",
        )
        return response


class SSOCallbackView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter("code", str), OpenApiParameter("state", str)],
        responses={302: None},
    )
    def get(self, request: Request, provider: str) -> HttpResponseRedirect:
        config = sso.get_provider(provider)
        if config is None:
            raise NotFound()
        try:
            if request.query_params.get("error"):
                raise sso.SSOError("denied")
            state = sso.read_state(
                request.COOKIES.get(sso.STATE_COOKIE, ""), request.query_params.get("state", "")
            )
            claims = sso.exchange(config, request.query_params.get("code", ""), state)
            user = sso.match_user(config, claims, intent=state["i"])
        except sso.SSOError as exc:
            response = _sso_redirect_failure(exc.code)
            response.delete_cookie(sso.STATE_COOKIE, path="/api/v1/auth/sso/")
            return response

        result = auth._begin_or_complete(request._request, user, method=f"sso_{provider}",
                                         remember=False)  # fmt: skip
        if result.mfa_required:
            target = f"{settings.APP_URL}/login?mfa=1"
        elif state["o"]:
            from tutortrack.tenancy.models import Organisation

            org = Organisation.objects.filter(pk=state["o"]).first()
            target = (
                f"{org.base_url}/auth/continue?handoff={handoff_token(user, org.pk)}"
                f"&next={state['x']}"
                if org is not None
                else f"{settings.APP_URL}{state['x']}"
            )
        elif state["i"] == "signup":
            target = f"{settings.APP_URL}/signup"
        else:
            target = f"{settings.APP_URL}{state['x']}"
        response = HttpResponseRedirect(target)
        response.delete_cookie(sso.STATE_COOKIE, path="/api/v1/auth/sso/")
        return response


# --- me -------------------------------------------------------------------------------------------


def me_payload(request: Request) -> dict[str, Any]:
    user = request.user
    organisation = getattr(request, "organisation", None)
    membership = getattr(request, "membership", None)
    impersonator = getattr(request._request, "impersonator", None)
    state = getattr(request._request, "impersonation", None) or {}
    return {
        "user": UserSerializer(user).data,
        "organisation": (
            {
                "id": organisation.pk,
                "name": organisation.name,
                "slug": organisation.slug,
                "status": organisation.status,
                "mode": organisation.mode,
            }
            if organisation is not None
            else None
        ),
        "membership": (
            {"id": membership.pk, "role": membership.role, "branch_scope": membership.branch_scope}
            if membership is not None
            else None
        ),
        "permissions": rbac.permissions_for(user) if organisation is not None else {},
        "features": flags.enabled_flags() if organisation is not None else {},
        "impersonator": (
            {
                "id": impersonator.pk,
                "email": impersonator.email,
                "name": impersonator.get_full_name(),
                "write": bool(state.get("write")),
            }
            if impersonator is not None
            else None
        ),
    }


@method_decorator(ensure_csrf_cookie, name="dispatch")
class MeView(APIView):
    """Who am I here: profile, organisation, role, effective permissions, features."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=MeSerializer)
    def get(self, request: Request) -> Response:
        return Response(me_payload(request))

    @extend_schema(request=UserSerializer, responses=MeSerializer)
    def patch(self, request: Request) -> Response:
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_profile(_user(request), **serializer.validated_data)
        return Response(me_payload(request))


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordChangeSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        data = _validated(PasswordChangeSerializer, request)
        try:
            auth.change_password(
                request._request, _user(request), data["current_password"], data["new_password"]
            )
        except DjangoValidationError as exc:
            raise _password_errors(exc) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Your signed-in sessions; delete one to sign it out (FR-03-3)."""

    serializer_class = SessionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self) -> QuerySet[UserSession]:
        if getattr(self, "swagger_fake_view", False):
            return UserSession.objects.none()
        return UserSession.objects.filter(user=_user(self.request), revoked_at__isnull=True)

    def perform_destroy(self, instance: UserSession) -> None:
        auth.revoke_session(instance)

    @extend_schema(
        request=None,
        responses=inline_serializer("SessionsRevoked", {"revoked": serializers.IntegerField()}),
    )
    @action(detail=False, methods=["post"], url_path="revoke-all")
    def revoke_all(self, request: Request) -> Response:
        """Sign out every other device."""
        count = auth.revoke_all_sessions(
            _user(request), except_id=request.session.get(auth.SID_KEY)
        )
        return Response({"revoked": count})


class TOTPSetupView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=TOTPSetupSerializer)
    def post(self, request: Request) -> Response:
        import segno

        device, uri = auth.start_totp_setup(_user(request))
        svg = segno.make(uri, error="m").svg_inline(scale=4, dark="#111827", light="#ffffff")
        return Response(
            {"device_id": device.pk, "secret": device.secret, "otpauth_uri": uri, "qr_svg": svg}
        )


class TOTPConfirmView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa"

    @extend_schema(request=TOTPConfirmSerializer, responses=RecoveryCodesSerializer)
    def post(self, request: Request) -> Response:
        data = _validated(TOTPConfirmSerializer, request)
        codes = auth.confirm_totp(_user(request), str(data["device_id"]), data["code"])
        return Response({"recovery_codes": codes})


def _require_password(request: Request) -> None:
    password = _validated(PasswordConfirmSerializer, request)["password"]
    if not request.user.check_password(password):
        raise auth.AuthenticationFailed("Your password is incorrect.")


class MFADisableView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordConfirmSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        _require_password(request)
        auth.disable_mfa(_user(request))
        return Response(status=status.HTTP_204_NO_CONTENT)


class RecoveryCodesView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PasswordConfirmSerializer, responses=RecoveryCodesSerializer)
    def post(self, request: Request) -> Response:
        _require_password(request)
        if not _user(request).has_mfa:
            raise BusinessRuleViolation("Set up an authenticator app first.")
        return Response({"recovery_codes": auth.regenerate_recovery_codes(_user(request))})


# --- team -----------------------------------------------------------------------------------------


class MembershipFilter(filters.FilterSet):
    # Declared explicitly: auto-generated filters query the (tenant-scoped) default manager
    # at class-creation time, which fails during OpenAPI generation.
    role = filters.ChoiceFilter(choices=Membership.Role.choices)
    status = filters.ChoiceFilter(choices=Membership.Status.choices)

    class Meta:
        model = Membership
        fields: list[str] = []


class InvitationFilter(filters.FilterSet):
    role = filters.ChoiceFilter(choices=Membership.Role.choices)
    status = filters.ChoiceFilter(choices=Invitation.Status.choices)

    class Meta:
        model = Invitation
        fields: list[str] = []


TEAM_PERMS = HasMethodPermission.for_(
    {"GET": "team.view", "PATCH": "team.manage", "DELETE": "team.manage", "POST": "team.invite"}
)


class MembershipViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Team members. ``DELETE`` removes the member's access to this organisation."""

    model = Membership
    serializer_class = MembershipSerializer
    permission_classes = [IsAuthenticated, HasOrganisation, TEAM_PERMS]
    filterset_class = MembershipFilter

    def get_tenant_queryset(self) -> QuerySet[Membership]:
        qs = Membership.objects.select_related("user").exclude(status=Membership.Status.REMOVED)
        return scope_queryset(self.request.user, qs, "team.view")

    @extend_schema(request=MembershipUpdateSerializer, responses=MembershipSerializer)
    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = _validated(MembershipUpdateSerializer, request)
        membership = services.update_membership(self.get_object(), **data)
        return Response(MembershipSerializer(membership, context={"request": request}).data)

    def perform_destroy(self, instance: Membership) -> None:
        services.remove_member(instance)


class InvitationViewSet(
    TenantScopedViewMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Invitations. ``DELETE`` revokes; ``resend`` sends a fresh 7-day link."""

    model = Invitation
    serializer_class = InvitationSerializer
    permission_classes = [
        IsAuthenticated,
        HasOrganisation,
        HasMethodPermission.for_({"GET": "team.view", "*": "team.invite"}),
    ]
    filterset_class = InvitationFilter

    def get_tenant_queryset(self) -> QuerySet[Invitation]:
        return Invitation.objects.all()

    def perform_create(self, serializer: Any) -> None:
        data = serializer.validated_data
        serializer.instance = services.invite(
            data["email"],
            role=data["role"],
            branch_scope=data.get("branch_scope", Membership.BranchScope.ALL),
            branches=data.get("branch_ids", []),
            title=data.get("title", ""),
        )

    def perform_destroy(self, instance: Invitation) -> None:
        services.revoke_invitation(instance)

    @extend_schema(request=None, responses=InvitationSerializer)
    @action(detail=True, methods=["post"])
    def resend(self, request: Request, pk: Any = None) -> Response:
        invitation = services.resend_invitation(self.get_object())
        return Response(self.get_serializer(invitation).data)

    @extend_schema(request=BulkInviteSerializer, responses=BulkInviteResultSerializer)
    @action(detail=False, methods=["post"])
    def bulk(self, request: Request) -> Response:
        data = _validated(BulkInviteSerializer, request)
        invited, skipped = [], {}
        for email in dict.fromkeys(e.lower() for e in data["emails"]):
            try:
                services.invite(email, role=data["role"])
                invited.append(email)
            except BusinessRuleViolation as exc:
                skipped[email] = str(exc.detail)
        return Response({"invited": invited, "skipped": skipped})


def _organisation_or_404(request: Request) -> Any:
    organisation = getattr(request, "organisation", None)
    if organisation is None:
        raise NotFound()
    return organisation


class InvitationLookupView(Throttled):
    """Public: what an invitation link is for (shown on the accept page)."""

    permission_classes = [AllowAny]
    throttle_scope = "verify_email"

    @extend_schema(
        parameters=[OpenApiParameter("token", str)], responses=InvitationLookupSerializer
    )
    def get(self, request: Request) -> Response:
        organisation = _organisation_or_404(request)
        try:
            invitation = services.invitation_for_token(request.query_params.get("token", ""))
        except InvalidToken as exc:
            raise NotFound("This invitation is invalid or has expired.") from exc
        return Response(
            {
                "email": invitation.email,
                "role": invitation.role,
                "organisation_name": organisation.name,
                "account_exists": User.objects.filter(email=invitation.email).exists(),
                "expires_at": invitation.expires_at,
            }
        )


class AcceptInvitationView(Throttled):
    """Accept an invitation: signed in as the invited email, or create the account."""

    permission_classes = [AllowAny]
    throttle_scope = "verify_email"

    @extend_schema(request=AcceptInvitationSerializer, responses=MembershipSerializer)
    def post(self, request: Request) -> Response:
        _organisation_or_404(request)
        data = _validated(AcceptInvitationSerializer, request)
        try:
            if request.user.is_authenticated:
                membership = services.accept_invitation(data["token"], request.user)
            else:
                if not data.get("password") or not data.get("first_name"):
                    raise serializers.ValidationError(
                        {"password": ["Required."], "first_name": ["Required."]}
                    )
                user, membership = services.accept_invitation_with_new_account(
                    data["token"],
                    password=data["password"],
                    first_name=data["first_name"],
                    last_name=data.get("last_name", ""),
                )
                auth.complete_login(request._request, user, method="invitation")
        except InvalidToken as exc:
            raise NotFound("This invitation is invalid or has expired.") from exc
        except DjangoValidationError as exc:
            raise _password_errors(exc, "password") from exc
        return Response(
            MembershipSerializer(membership, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


# --- roles, permissions, impersonation ------------------------------------------------------------


class RolesView(APIView):
    permission_classes = [IsAuthenticated, HasOrganisation]

    @extend_schema(responses=RoleSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(
            [
                {
                    "key": r.key,
                    "name": r.name,
                    "description": r.description,
                    "is_builtin": True,
                    "is_staff": r.is_staff,
                    "grants": [f"{g.pattern}:{g.scope}" for g in r.grants],
                    "denies": list(r.denies),
                }
                for r in ROLES.values()
            ]
        )


class PermissionsView(APIView):
    """The permission registry (for the roles matrix)."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses=PermissionSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(
            [
                {"codename": p.codename, "category": p.category, "description": p.description}
                for p in all_permissions().values()
            ]
        )


class ImpersonateView(APIView):
    """View the app as a tutor, client or student (read-only unless ``write``)."""

    permission_classes = [IsAuthenticated, HasOrganisation]

    @extend_schema(request=ImpersonateSerializer, responses={204: None})
    def post(self, request: Request) -> Response:
        data = _validated(ImpersonateSerializer, request)
        if getattr(request._request, "impersonator", None) is not None:
            raise PermissionDenied("Stop the current impersonation first.")
        impersonation.start(request._request, data["membership_id"], write=data["write"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class StopImpersonationView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={204: None})
    def post(self, request: Request) -> Response:
        impersonation.stop(request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)
