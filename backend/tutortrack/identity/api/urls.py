from django.urls import path
from rest_framework.routers import SimpleRouter

from . import support_views, views

router = SimpleRouter(trailing_slash=False)
router.register("me/sessions", views.SessionViewSet, basename="me-sessions")
router.register("memberships", views.MembershipViewSet, basename="memberships")
router.register("invitations", views.InvitationViewSet, basename="invitations")

urlpatterns = [
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("auth/mfa/verify", views.MFAVerifyView.as_view(), name="auth-mfa-verify"),
    path("auth/magic-link", views.MagicLinkView.as_view(), name="auth-magic-link"),
    path(
        "auth/magic-link/verify", views.MagicLinkVerifyView.as_view(), name="auth-magic-link-verify"
    ),
    path("auth/password/reset", views.PasswordResetView.as_view(), name="auth-password-reset"),
    path(
        "auth/password/reset/confirm",
        views.PasswordResetConfirmView.as_view(),
        name="auth-password-reset-confirm",
    ),
    path("auth/sso/providers", views.SSOProvidersView.as_view(), name="auth-sso-providers"),
    path("auth/sso/<slug:provider>/start", views.SSOStartView.as_view(), name="auth-sso-start"),
    path(
        "auth/sso/<slug:provider>/callback",
        views.SSOCallbackView.as_view(),
        name="auth-sso-callback",
    ),
    path("me", views.MeView.as_view(), name="me"),
    path("me/password", views.PasswordChangeView.as_view(), name="me-password"),
    path("me/logins", views.MyLoginsView.as_view(), name="me-logins"),
    path("me/mfa/totp", views.TOTPSetupView.as_view(), name="me-mfa-totp"),
    path("me/mfa/totp/confirm", views.TOTPConfirmView.as_view(), name="me-mfa-totp-confirm"),
    path("me/mfa/disable", views.MFADisableView.as_view(), name="me-mfa-disable"),
    path("me/mfa/recovery-codes", views.RecoveryCodesView.as_view(), name="me-recovery-codes"),
    path("invitations/lookup", views.InvitationLookupView.as_view(), name="invitation-lookup"),
    path("invitations/accept", views.AcceptInvitationView.as_view(), name="invitation-accept"),
    path("roles", views.RolesView.as_view(), name="roles"),
    path("permissions", views.PermissionsView.as_view(), name="permissions"),
    path("support-access", support_views.SupportAccessView.as_view(), name="support-access"),
    path(
        "support-access/grants",
        support_views.SupportGrantsView.as_view(),
        name="support-access-grants",
    ),
    path(
        "support-access/grants/<uuid:pk>/revoke",
        support_views.RevokeSupportGrantView.as_view(),
        name="support-access-revoke",
    ),
    path("support/enter", support_views.SupportEnterView.as_view(), name="support-enter"),
    path("impersonate", views.ImpersonateView.as_view(), name="impersonate"),
    path("impersonate/stop", views.StopImpersonationView.as_view(), name="impersonate-stop"),
    *router.urls,
]
