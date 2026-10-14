from django.urls import path
from rest_framework.routers import SimpleRouter

from . import account_views, support_views, views
from . import phase2_views as p2

router = SimpleRouter(trailing_slash=False)
router.register("me/sessions", views.SessionViewSet, basename="me-sessions")
router.register("memberships", views.MembershipViewSet, basename="memberships")
router.register("invitations", views.InvitationViewSet, basename="invitations")
router.register("custom-roles", p2.CustomRoleViewSet, basename="custom-roles")

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
    path("auth/passkey/options", p2.PasskeyAuthOptionsView.as_view(), name="auth-passkey-options"),
    path("auth/passkey/verify", p2.PasskeyVerifyView.as_view(), name="auth-passkey-verify"),
    path("auth/org-sso", p2.OrgSSOInfoView.as_view(), name="auth-org-sso"),
    path("auth/org-sso/start", p2.OrgSSOStartView.as_view(), name="auth-org-sso-start"),
    path("auth/org-sso/callback", p2.OrgSSOCallbackView.as_view(), name="auth-org-sso-callback"),
    path("auth/org-sso/acs", p2.OrgSSOAcsView.as_view(), name="auth-org-sso-acs"),
    path("auth/org-sso/metadata", p2.OrgSSOMetadataView.as_view(), name="auth-org-sso-metadata"),
    path("security/sso", p2.OrganisationSSOView.as_view(), name="security-sso"),
    path("me/passkeys", p2.PasskeyListView.as_view(), name="me-passkeys"),
    path(
        "me/passkeys/options", p2.PasskeyRegisterOptionsView.as_view(), name="me-passkeys-options"
    ),
    path("me/passkeys/register", p2.PasskeyRegisterView.as_view(), name="me-passkeys-register"),
    path("me/passkeys/<uuid:pk>", p2.PasskeyDetailView.as_view(), name="me-passkey"),
    path("me", views.MeView.as_view(), name="me"),
    path("me/password", views.PasswordChangeView.as_view(), name="me-password"),
    path("me/logins", views.MyLoginsView.as_view(), name="me-logins"),
    path(
        "me/account-deletion",
        account_views.AccountDeletionView.as_view(),
        name="me-account-deletion",
    ),
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
