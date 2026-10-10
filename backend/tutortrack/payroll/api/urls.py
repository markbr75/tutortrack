from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter(trailing_slash=False)
router.register("pay-items", views.PayItemViewSet, basename="pay-items")
router.register("expense-categories", views.ExpenseCategoryViewSet, basename="expense-categories")
router.register("expenses", views.ExpenseViewSet, basename="expenses")
router.register("pay-runs", views.PayRunViewSet, basename="pay-runs")
router.register("pay-statements", views.StatementViewSet, basename="pay-statements")

urlpatterns = [
    path("tutors/<uuid:pk>/pay-profile", views.PayProfileView.as_view(), name="pay-profile"),
    path("me/pay-profile", views.MyPayProfileView.as_view(), name="my-pay-profile"),
    path("me/pay-profile/self-billing", views.AgreeSelfBillingView.as_view(),
         name="my-self-billing"),
    path("me/pay-profile/stripe", views.StripeOnboardingView.as_view(), name="my-stripe-payouts"),
    path("me/earnings", views.MyEarningsView.as_view(), name="my-earnings"),
    path("payroll/originator", views.OriginatorView.as_view(), name="payroll-originator"),
    path("payouts/<uuid:pk>/fail", views.FailPayoutView.as_view(), name="payout-fail"),
    *router.urls,
]  # fmt: skip
