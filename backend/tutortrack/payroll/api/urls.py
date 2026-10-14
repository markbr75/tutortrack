from django.urls import path
from rest_framework.routers import SimpleRouter

from . import tax_views, views

router = SimpleRouter(trailing_slash=False)
router.register("pay-items", views.PayItemViewSet, basename="pay-items")
router.register("expense-categories", views.ExpenseCategoryViewSet, basename="expense-categories")
router.register("expenses", views.ExpenseViewSet, basename="expenses")
router.register("pay-runs", views.PayRunViewSet, basename="pay-runs")
router.register("pay-statements", views.StatementViewSet, basename="pay-statements")
router.register("payroll/tax-forms", tax_views.TaxFormFilingViewSet, basename="tax-forms")

urlpatterns = [
    path("tutors/<uuid:pk>/pay-profile", views.PayProfileView.as_view(), name="pay-profile"),
    path("me/pay-profile", views.MyPayProfileView.as_view(), name="my-pay-profile"),
    path("me/pay-profile/self-billing", views.AgreeSelfBillingView.as_view(),
         name="my-self-billing"),
    path("me/pay-profile/stripe", views.StripeOnboardingView.as_view(), name="my-stripe-payouts"),
    path("me/earnings", views.MyEarningsView.as_view(), name="my-earnings"),
    path("me/earnings/annual", views.MyAnnualEarningsView.as_view(), name="my-annual-earnings"),
    path("tutors/<uuid:pk>/earnings/annual", views.TutorAnnualEarningsView.as_view(),
         name="tutor-annual-earnings"),
    path("payroll/originator", views.OriginatorView.as_view(), name="payroll-originator"),
    path("payouts/<uuid:pk>/fail", views.FailPayoutView.as_view(), name="payout-fail"),
    # Phase 3 (E12-T12): US tax identity and 1099-NEC data
    path("tutors/<uuid:pk>/tax-identity", tax_views.TaxIdentityView.as_view(),
         name="tax-identity"),
    path("me/tax-identity", tax_views.MyTaxIdentityView.as_view(), name="my-tax-identity"),
    path("me/tax-summary", tax_views.MyTaxSummaryView.as_view(), name="my-tax-summary"),
    path("payroll/tax-years/<int:year>/1099", tax_views.Form1099View.as_view(),
         name="form-1099"),
    path("payroll/tax-years/<int:year>/1099/finalise", tax_views.Form1099FinaliseView.as_view(),
         name="form-1099-finalise"),
    path("payroll/tax-years/<int:year>/1099/export", tax_views.Form1099ExportView.as_view(),
         name="form-1099-export"),
    *router.urls,
]  # fmt: skip
