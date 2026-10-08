from django.urls import path
from rest_framework.routers import SimpleRouter

from .onboarding import OnboardingStateView, OnboardingStepView
from .signup import (
    HandoffView,
    ResendVerificationView,
    SignupConfigView,
    SignupView,
    SlugCheckView,
    VerifyEmailView,
)
from .views import BranchViewSet, OrganisationView, SettingsView

router = SimpleRouter(trailing_slash=False)
router.register("branches", BranchViewSet, basename="branches")

urlpatterns = [
    path("organisation", OrganisationView.as_view(), name="organisation"),
    path("settings/<slug:area>", SettingsView.as_view(), name="settings"),
    path("signup", SignupView.as_view(), name="signup"),
    path("signup/config", SignupConfigView.as_view(), name="signup-config"),
    path("signup/slug-check", SlugCheckView.as_view(), name="signup-slug-check"),
    path("signup/verify-email", VerifyEmailView.as_view(), name="signup-verify-email"),
    path(
        "signup/resend-verification",
        ResendVerificationView.as_view(),
        name="signup-resend-verification",
    ),
    path("auth/handoff", HandoffView.as_view(), name="auth-handoff"),
    path("onboarding/state", OnboardingStateView.as_view(), name="onboarding-state"),
    path("onboarding/<slug:step>", OnboardingStepView.as_view(), name="onboarding-step"),
    *router.urls,
]
